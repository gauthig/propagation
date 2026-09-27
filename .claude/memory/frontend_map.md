---
name: frontend-map
description: "D3 map layers, heatmap canvas drawing rules, skip circle, greyline layer, and rendering gotchas"
metadata:
  node_type: memory
  type: project
  originSessionId: 67f4cc15-833d-49d0-982f-a2dd3f24bb7c
  modified: 2026-09-27T18:07:29.926Z
---

All in `templates/index.html` (single file, no build step; D3 v7 + d3-geo-projection 4 +
topojson-client 3 from jsDelivr).

**Projection:** `buildProjection(lon, W, H)` = Winkel Tripel (fallback NaturalEarth1) rotated to
the QTH longitude, `fitSize` to the viewport; rebuilt on resize and on QTH change.

**Layers, bottom → top:** `#worldmap` SVG (ocean, graticule, countries — Antarctica id 10 pale,
borders, `#city-g`, `#overlay-g` = QTH dot + skip circle) → `#heat-canvas` (CSS `blur(9px)`,
opacity 0.85) → `#greyline-layer` SVG (twilight band, terminator, sub-solar dot; drawn above the
blur so it stays crisp).

**Heat canvas (`drawHeatCanvas`):** 20 px blobs on an offscreen canvas, alpha capped at 145/255.
Skips strength < 0.12, fades 0.12–0.35 (WSPR-validated cutoff); `heatColor` red→green. Returns early
while the canvas is 0×0 (page opened in a background tab) — `onResize` redraws later.

**Skip circle:** `estimateSkipKm(freq, lat, lon, sfi)` — for 24 bearings, shortest single hop whose
*midpoint* foF2 (`estimateFoF2`, mirrors `_fof2`) × `hopMFactor` ≥ f; min over bearings, cap
3,500 km; 150 = NVIS (no circle). Constants must match `propagation.py`.

**Gotchas**
- `drawBaseMap()` does `svg.selectAll('*').remove()` → always follow with `drawCities()` +
  `updateOverlay()` (which also redraws the greyline).
- Greyline band polygon is `[ring93, reverse(ring78)]`; reversing the 93° ring fills the complement.
  Terminator is drawn as a LineString (a Polygon adds map-edge clip lines).
- Use `d3.geoCircle()` for geographic rings, not screen circles.
- Avoid numeric separators like `900_000` in JS (SyntaxError in some environments).
- Local dev: Flask caches the template and `/` has max-age 600 → restart the server and load
  `/?nocache=N` after template edits.

See [[ui-features]] for panel controls and persistence.
