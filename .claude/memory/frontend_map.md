---
name: frontend-map
description: "D3 map setup, canvas heatmap, city rendering, session persistence, and known gotchas"
metadata: 
  node_type: memory
  type: project
  originSessionId: 67f4cc15-833d-49d0-982f-a2dd3f24bb7c
---

## Map rendering (`templates/index.html`)

**Projection:** Winkel Tripel via `d3.geoWinkelTripel()` from `d3-geo-projection@4`.
- CDN UMD bundle extends the global `d3` object
- Falls back to `d3.geoNaturalEarth1()` if CDN fails
- `fitSize([W, H], {type:'Sphere'})` scales full globe to viewport
- `buildProjection(lon, W, H)` used everywhere — rotates to `[-lon, 0]` to center on QTH longitude

**Layer order (bottom to top in SVG):**
1. Sphere path (ocean `#1e4d7b`)
2. Graticule (30° grid, subtle)
3. Country polygons — Antarctica (id===10) gets `#c8d8e4`, others `#4a7055`
4. Country borders (`#2d422d`, 0.4px)
5. Sphere outline ring
6. `#city-g` group — ~46 city dots + double-rendered labels
7. `#overlay-g` group — QTH dot + skip-zone circle

**Canvas heatmap (separate `<canvas>`):**
- CSS: `opacity:0.85; filter:blur(9px)`
- Offscreen canvas (`_offCanvas`) used to cap per-pixel alpha at 145/255 (~57%) so map shows through dense coverage
- Per-blob alpha: `0.25 + strength * 0.30` (weak = faint, strong = solid)
- `heatColor(s)` gradient: deep red (0.00) → red (0.20) → orange (0.40) → yellow (0.60) → lime (0.78) → green (1.00)
- `HEAT_RADIUS = 20` px per blob
- Canvas and SVG both resized on `window.resize`

**Overlays (`updateOverlay()`):**
- QTH dot: 7px cyan circle with SVG glow filter (`#qth-glow`)
- Skip zone: gray dashed ring, drawn only if > 300 km; radius from `estimateSkipKm(freq, sfi)` JS formula
- **No 500 km reference ring** (removed — was `QTH_CIRCLE_KM`)
- Both rings use `d3.geoCircle()` for proper geographic projection

**City labels:** `drawCities()` called after every `drawBaseMap()`. Double-rendered (shadow + main text). `anchor` property per city controls label placement.

**Known gotchas:**
- `svg.selectAll('*').remove()` in `drawBaseMap()` wipes `#overlay-g` and `#city-g` — always call `drawCities()` + `updateOverlay()` after `drawBaseMap()`
- `d3.geoCircle()` required for skip ring (not screen circles)
- `900_000` numeric separator syntax caused SyntaxError in some environments — use `900000`

## Session persistence (localStorage)

`initSession()` is called at boot (after `initMap()`, before `loadBand()`):
- Reads `localStorage['hf_callsign']` — shows popup if null (never set), shows badge if non-empty, skips popup if empty string
- Reads `hf_qth_lat`, `hf_qth_lon`, `hf_qth_label` — if valid, sets `qthLat/qthLon` and rebuilds projection before first `loadBand()` so the heatmap loads from the restored location immediately

`onQTHSet(lat, lon, meta)` saves `hf_qth_lat/lon/label` to localStorage every time the user sets a QTH.

Callsign saved via `saveCallsign()` → `localStorage['hf_callsign']`. Skipped via `skipCallsign()` → saves `''` so popup never re-appears.

**Performance:** ~2,300 grid points rendered as canvas arcs in ~5 ms. Single draw on data arrival.
