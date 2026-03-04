# 🌿 Camporella Finder

> **Vibe-coded** with [GitHub Copilot](https://github.com/features/copilot) + Claude Sonnet.  
> Un'idea malsana, eseguita seriamente.

A Google Maps-style web app that analyzes satellite/OSM data around your location and suggests the **best spots for a camporella** — scoring each candidate on privacy, accessibility, terrain type, and distance from buildings.

---

## Screenshot

![map view with scored spots](https://placehold.co/900x500/0f0f0f/4ade80?text=Camporella+Finder)

---

## How it works

1. Open the app and **click on the map** (or hit 📍 to use your GPS)
2. Adjust the **search radius** (500 m – 3 km)
3. Hit **🔍 Analizza** — the backend:
   - Queries the free [Overpass API](https://overpass-api.de/) (OpenStreetMap data, no key needed)
   - Builds a ~55 m grid of candidate points inside the radius
   - Scores every candidate 0–100 across 4 dimensions
   - Returns the top 8 geographically spread results
4. Results appear on the map as numbered markers and in the side panel with score breakdown

### Scoring breakdown

| Component | Weight | Logic |
|---|---|---|
| 🛣 Privacy from main roads | 25 pt | distance from motorway / primary / secondary only |
| 🚗 Car accessibility | 35 pt | sweet spot 50–150 m from a car-driveable road (park & short walk) |
| 🏚 Distance from buildings | 20 pt | max score at ≥ 300 m |
| 🌿 Terrain / cover | 20 pt | forest/scrub = top; unknown = neutral; open field = disqualified |

Road types are split into three tiers:
- **Main** (motorway, trunk, primary, secondary) — noise/exposure source
- **Driveable** (tertiary, residential, service, unclassified, track) — where you park
- **Walkable** (path, footway, cycleway, bridleway) — ignored for parking purposes

**Hard disqualifiers:**
- On or within 25 m of any road
- Water, residential, commercial, industrial, military land
- **Open agricultural/exposed land** (farmland, meadow, grass, orchard, vineyard) — visible, often private
- More than **200 m from a car-driveable road** — no tractor, no 20-minute hike

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3 + [Flask](https://flask.palletsprojects.com/) |
| Map | [Leaflet.js](https://leafletjs.com/) + ESRI World Imagery satellite tiles |
| OSM data | [Overpass API](https://overpass-api.de/) (free, no API key) |
| DB | None — everything is computed at runtime |

---

## Requirements

- Python 3.9+
- No external API keys required

---

## Quickstart

```bash
git clone https://github.com/yourusername/camporellap
cd camporellap

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python app.py
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080) in your browser.

**To stop the server:** `Ctrl+C` in the terminal.  
**To kill a background instance:** `pkill -f "python app.py"`

---

## Project structure

```
camporellap/
├── app.py               # Flask backend + scoring algorithm
└── templates/
    └── index.html       # Single-page frontend (Leaflet + vanilla JS)
```

---

## Notes & caveats

- OSM data quality varies by region — rural Italy is well mapped, remote areas less so
- The Overpass API is a public free service; large radii (> 2 km) may be slow
- Land type detection depends on OSM `landuse`/`natural` polygon coverage; unmapped areas return `unknown` terrain
- This app does not store any data — no DB, no cookies, no logs

---

## License

WTFPL — do whatever you want with it. Responsibly.
