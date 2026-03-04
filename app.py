from flask import Flask, render_template, request, jsonify
import requests
import math
import json

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def haversine(lat1, lon1, lat2, lon2):
    """Distance in metres between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _project(lat, lng, cos_lat):
    """Cheap flat-earth projection to metres (good for < 5 km)."""
    return lng * 111_320 * cos_lat, lat * 111_320


def _seg_dist(px, py, ax, ay, bx, by):
    """Distance from point P to segment AB (all in metres)."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def min_dist_to_ways(lat, lng, ways, cos_lat):
    """Minimum distance in metres from a point to any polyline in *ways*."""
    if not ways:
        return float("inf")
    px, py = _project(lat, lng, cos_lat)
    best = float("inf")
    for way in ways:
        for i in range(len(way) - 1):
            ax, ay = _project(way[i][0], way[i][1], cos_lat)
            bx, by = _project(way[i + 1][0], way[i + 1][1], cos_lat)
            d = _seg_dist(px, py, ax, ay, bx, by)
            if d < best:
                best = d
    return best


def point_in_polygon(lat, lng, polygon, cos_lat):
    """Ray-casting inside test. polygon is list of (lat, lon) pairs."""
    if len(polygon) < 3:
        return False
    px, py = _project(lat, lng, cos_lat)
    poly = [_project(p[0], p[1], cos_lat) for p in polygon]
    inside = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------------------
# OSM / Overpass
# ---------------------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

HIGHWAY_MAIN = {
    "motorway", "trunk", "primary", "secondary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
}
# Roads where you can actually drive and park a car
HIGHWAY_DRIVEABLE = {
    "tertiary", "tertiary_link", "residential", "living_street",
    "service", "unclassified", "track",
}
# Foot/bike-only paths — NOT suitable for parking
HIGHWAY_WALKABLE = {
    "path", "footway", "cycleway", "bridleway", "pedestrian", "steps",
}

# Genuinely good terrain: covered/hidden
LANDTYPE_GOOD = {"wood", "forest", "scrub", "heath", "fell", "moor"}
# Hard bad: water, urban, AND open agricultural fields (private, exposed, no cover)
LANDTYPE_BAD  = {
    "water", "reservoir", "basin",
    "residential", "commercial", "industrial", "retail", "construction", "military",
    "farmland", "meadow", "grass", "grassland", "orchard", "vineyard",
    "allotments", "greenhouse_horticulture",
}


def fetch_osm(lat, lng, radius):
    query = f"""
[out:json][timeout:40];
(
  way["highway"](around:{radius},{lat},{lng});
  way["building"](around:{radius},{lat},{lng});
  way["landuse"](around:{radius},{lat},{lng});
  way["natural"](around:{radius},{lat},{lng});
  way["leisure"](around:{radius},{lat},{lng});
);
out body;
>;
out skel qt;
"""
    r = requests.post(OVERPASS_URL, data={"data": query}, timeout=45)
    r.raise_for_status()
    return r.json()


def parse_osm(raw):
    nodes = {e["id"]: (e["lat"], e["lon"])
             for e in raw["elements"] if e["type"] == "node"}

    roads_main, roads_driveable, roads_walkable, buildings = [], [], [], []
    land_polygons = {}   # landtype -> [polygon, ...]

    for el in raw["elements"]:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        coords = [nodes[n] for n in el.get("nodes", []) if n in nodes]
        if not coords:
            continue

        hw = tags.get("highway", "")
        if hw in HIGHWAY_MAIN:
            roads_main.append(coords)
        elif hw in HIGHWAY_DRIVEABLE:
            roads_driveable.append(coords)
        elif hw in HIGHWAY_WALKABLE or (hw and hw not in HIGHWAY_MAIN):
            roads_walkable.append(coords)

        if "building" in tags:
            buildings.append(coords)

        lt = tags.get("landuse") or tags.get("natural") or tags.get("leisure")
        if lt:
            land_polygons.setdefault(lt, []).append(coords)

    return roads_main, roads_driveable, roads_walkable, buildings, land_polygons


def get_land_quality(lat, lng, land_polygons, cos_lat):
    detected = [lt for lt, polys in land_polygons.items()
                if any(point_in_polygon(lat, lng, p, cos_lat) for p in polys)]
    for lt in detected:
        if lt in LANDTYPE_BAD:
            return "bad", lt
    for lt in detected:
        if lt in LANDTYPE_GOOD:
            return "good", lt
    return ("neutral", detected[0]) if detected else ("unknown", "—")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_point(lat, lng, roads_main, roads_driveable, roads_walkable,
                buildings, land_polygons, cos_lat):
    d_main      = min_dist_to_ways(lat, lng, roads_main,      cos_lat)
    d_drive     = min_dist_to_ways(lat, lng, roads_driveable, cos_lat)
    d_walk      = min_dist_to_ways(lat, lng, roads_walkable,  cos_lat)
    d_any_road  = min(d_main, d_drive, d_walk)
    d_build     = min_dist_to_ways(lat, lng, buildings,       cos_lat)

    # ── Hard disqualifiers ──────────────────────────────────────────────────
    if d_any_road < 25:
        return None          # point is ON a road

    lq, lt = get_land_quality(lat, lng, land_polygons, cos_lat)
    if lq == "bad":
        return None          # water / urban / military

    # PRIMARY gate: must be within 200 m of a car-driveable road.
    # 200 m = short walk, you can see roughly where you parked.
    # Footpaths/tracks-only = no.
    if d_drive > 200:
        return None

    # No secondary gate needed — d_drive <= 200 is already strict enough.

    # ── Component scores (max 25 + 35 + 20 + 20 = 100) ─────────────────────

    # 1. Privacy from main arterial roads (0-25 pts)
    #    Only fast/busy roads matter for noise and sightlines.
    #    The quiet lane you parked on does NOT count against privacy.
    main_privacy = min(d_main / 300.0, 1.0) * 25 if d_main < float("inf") else 25

    # 2. Car accessibility (0-35 pts)
    #    Gate ensures d_drive <= 200 m. Sweet spot: 50-150 m (short walk, hidden).
    if d_drive < 20:
        access = 5           # roadside — too exposed
    elif d_drive <= 50:
        access = 35 * (d_drive - 20) / 30.0       # ramp up
    elif d_drive <= 150:
        access = 35.0        # ideal: 50-150 m, short walk through vegetation
    else:
        access = 35 * (1 - (d_drive - 150) / 50.0)   # 150-200 m: ramp down to 0

    # 3. Distance from buildings (0-20 pts)
    build_priv = min(d_build / 300.0, 1.0) * 20 if d_build < float("inf") else 20

    # 4. Terrain / land type (0-20 pts)
    #    Forest/scrub = hidden + cover; open field = visible from road
    if lq == "good":
        terrain_pts = {"wood": 20, "forest": 20, "scrub": 16, "heath": 14,
                       "fell": 12, "moor": 12}.get(lt, 12)
    elif lq == "neutral":
        terrain_pts = 4      # open/exposed land — visible, often private property
    else:
        terrain_pts = 6      # unknown but not confirmed bad

    total = main_privacy + access + build_priv + terrain_pts

    return {
        "score":            round(total, 1),
        "main_road_dist":   round(d_main)  if d_main  < float("inf") else 9999,
        "access_road_dist": round(d_drive) if d_drive < float("inf") else 9999,
        "building_dist":    round(d_build) if d_build < float("inf") else 9999,
        "land_type":        lt,
        "land_quality":     lq,
        "offroad_walk_m":   round(d_drive) if d_drive < float("inf") else 9999,
        "components": {
            "main_road_privacy": round(main_privacy, 1),
            "accessibility":     round(access, 1),
            "building_privacy":  round(build_priv, 1),
            "terrain":           round(terrain_pts, 1),
        },
        "max_components": {"main_road_privacy": 25, "accessibility": 35,
                           "building_privacy": 20, "terrain": 20},
    }


# ---------------------------------------------------------------------------
# Candidate grid
# ---------------------------------------------------------------------------

def candidate_grid(center_lat, center_lng, radius=1400, step=55):
    cos_lat   = math.cos(math.radians(center_lat))
    d_lat_deg = step / 111_320
    d_lng_deg = step / (111_320 * cos_lat)
    pts = []
    lat = center_lat - radius / 111_320
    while lat <= center_lat + radius / 111_320:
        lng = center_lng - radius / (111_320 * cos_lat)
        while lng <= center_lng + radius / (111_320 * cos_lat):
            d = haversine(center_lat, center_lng, lat, lng)
            if 40 < d <= radius:
                pts.append((lat, lng))
            lng += d_lng_deg
        lat += d_lat_deg
    return pts


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    body   = request.get_json(force=True)
    lat    = float(body["lat"])
    lng    = float(body["lng"])
    radius = int(body.get("radius", 1400))

    try:
        raw = fetch_osm(lat, lng, radius + 600)
    except Exception as e:
        return jsonify({"error": f"Overpass API error: {e}"}), 502

    roads_main, roads_driveable, roads_walkable, buildings, land_polygons = parse_osm(raw)
    cos_lat    = math.cos(math.radians(lat))
    candidates = candidate_grid(lat, lng, radius)

    scored = []
    for clat, clng in candidates:
        r = score_point(clat, clng, roads_main, roads_driveable, roads_walkable,
                        buildings, land_polygons, cos_lat)
        if r is not None:
            r["lat"] = clat
            r["lng"] = clng
            r["dist_from_you"] = round(haversine(lat, lng, clat, clng))
            scored.append(r)

    scored.sort(key=lambda x: -x["score"])

    # Geographic spread: keep a result only if ≥ 200 m from all already-kept
    MIN_SPREAD = 200
    top = []
    for s in scored:
        if all(haversine(s["lat"], s["lng"], k["lat"], k["lng"]) >= MIN_SPREAD
               for k in top):
            top.append(s)
        if len(top) >= 8:
            break

    for i, s in enumerate(top):
        s["rank"] = i + 1

    return jsonify({
        "spots": top,
        "stats": {
            "candidates":      len(candidates),
            "valid":           len(scored),
            "roads_main":      len(roads_main),
            "roads_driveable": len(roads_driveable),
            "roads_walkable":  len(roads_walkable),
            "buildings":       len(buildings),
        },
    })


if __name__ == "__main__":
    app.run(debug=True, port=8080)
