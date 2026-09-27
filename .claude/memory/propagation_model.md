---
name: propagation-model
description: "foF2/MUF model, absorption, antenna factor model, band freqs, known limitations"
metadata: 
  node_type: memory
  type: project
  originSessionId: 67f4cc15-833d-49d0-982f-a2dd3f24bb7c
  modified: 2026-09-27T15:01:15.366Z
---

## Ionospheric model (`propagation.py` → `calculate_muf_map`)

Empirical F2-layer model — not ray-tracing (not VOACAP). Reworked 2026-09-27 (v2609.001)
after 20m showed no US coverage during the day; the old model's foF2 was ~half of real.

**Solar data sources (with fallback):**
1. `http://www.hamqsl.com/solarxml.php` — SFI, K-index, A-index, SSN, band conditions (HTTP only, not HTTPS)
2. NOAA SWPC JSON endpoints — fallback if hamqsl unreachable

**Path geometry:**
- Grid: 3° lat/lon, -75..+78 lat, -180..+177 lon; cells < 150 km from QTH dropped
- Hops: `n = ceil(dist / 3500 km)`, equal-length hops
- Reflection points = true great-circle hop midpoints (`_gc_point`)
- `_hop_geometry(hop_km)` — curved earth, 300 km F2 layer, min takeoff 3° → returns
  takeoff angle (also used by the antenna elevation pattern) and M-factor
  (~1.0 short hops → ~3.37 at 3,500 km)

**foF2 at each hop midpoint:**
```
peak = 3.0 + 0.055 * SFI                      # ~8.6 MHz at SFI 100 (mid-lat ionosonde typical)
cz   = cos(solar zenith) at midpoint, sun lagged 1 h (_F2_LAG_H) → peak ≈ 13:00 local
foF2 = max(peak * (0.33 + 0.67 * sqrt(max(cz, 0))), 1.0)   # _NIGHT_FLOOR = 0.33
```
Declination from day-of-year, so season/latitude come from the zenith angle (no separate lat factor).
Path MUF = min over hops of foF2 × M. Time uses UTC hour+minute.

**D-layer absorption (per hop, summed):**
`loss_dB = 677·(1+0.0037·SSN)·cos(χ)^0.75 / (f+1.4)² · M` (χ unlagged) →
strength × 10^(−loss/40). This is what fades 80m/40m on long daytime paths.

**Strength:** ratio = f/MUF → ≤1.0 → 1.0; 1.0–1.35 → `((1.35-r)/0.35)^0.7`; >1.35 → 0.
No below-MUF penalty any more (old 0.45–0.85 "below FOT" branch removed — it made
good low-ratio paths look weak). Then × absorption × `kp_penalty = max(0, 1-(K/9)·0.75)`
× antenna factor; cells ≤ 0.03 dropped.

**Tuning notes (2026-09-27):** night floor 0.38 painted faint red over the whole
night side on 20m; 0.30 killed 40m night short paths; 0.33 chosen. Constants were
calibrated against typical band behavior, not ionosonde data — validating against
Point Arguello (GIRO) or VOACAP is an open follow-up.

**Skip circle (frontend `estimateSkipKm` in index.html):** mirrors the server math
(`estimateFoF2`, `hopMFactor` — constants must stay in sync). For 24 bearings finds
the shortest hop whose *midpoint* foF2 × M ≥ f (median MUF), circle = min over
bearings, capped 3,500 km; returns 150 (no circle) when NVIS works. Using foF2 over
the QTH instead gave a max-size circle at sunrise while the map showed the US open.

**Band frequencies (`app.py → BAND_FREQS`):**
```
80m: 3.500–4.000 MHz     60m: 5.330–5.404 MHz
40m: 7.000–7.300 MHz     20m: 14.00–14.35 MHz
17m: 18.07–18.17 MHz     15m: 21.00–21.45 MHz
10m: 28.00–29.70 MHz
```

**Cache:** 20m and 40m pre-warmed every 15 min by background thread. Heatmap LRU key
includes UTC hour (not minute or SSN), so a cached map can be up to 1 h old.

## Antenna model (inside `calculate_muf_map`)

Applied multiplicatively after absorption and kp_penalty. Normalized so λ/4 vertical = 1.0. All antennas assume resonance and average ground (σ ≈ 5 mS/m).

- True bearing station → cell computed inline (vectorized)
- Takeoff angle = `elev` from `_hop_geometry` (curved earth, per-hop, min 3°)
- `_EL_NORM = 0.394` — normalization so dipole at 0.5λ broadside gives factor ≈ 1.30

**Vertical (`_vertical_factor`):**
- Omnidirectional; height_m ignored in UI (hidden when vertical selected)
- h < 0.15λ → factor scales from 0.3 (efficiency loss) — e.g. 30 ft on 80m caps at ~0.46
- 0.15–0.35λ (λ/4 sweet spot) → factor 1.0
- > 0.35λ → factor tapers down (pattern shifts upward)

**Dipole:**
- `dipole_orient` is wire azimuth in degrees (float): 0=N-S, 45=NE-SW, 90=E-W, 135=NW-SE
- `wire_az = dipole_orient % 180` (symmetric)
- Azimuth factor: `sin²(angle_from_wire)`, min 0.02
- Elevation factor: `|sin(π · h/λ · sin(takeoff))| / EL_NORM`, min 0.05

**Hex Beam:**
- Valid bands: 20m, 17m, 15m, 10m. Error shown and heatmap cleared for 80m/60m/40m.
- `beam_azimuth` in degrees (0–360); default 90 (East)
- `angle_off = |((bearing - baz + 180) % 360) - 180|`
- angle_off ≤ 30°: az_factor = 3.5 (full main beam, ~6 dBd)
- 30–90°: taper via cos²; floor 0.12
- > 90°: az_factor = 0.04 (~−19 dB rear)
- Same elevation model as dipole

**Known limitations:**
- Single hop-count threshold (3,500 km) causes small strength steps where n changes
- No sporadic-E, greyline enhancement, or transequatorial propagation
- No noise/SNR model — strength is a probability-like openness score
- Skip circle uses the median MUF; the map's 1.0–1.35 tail can show faint red inside it
