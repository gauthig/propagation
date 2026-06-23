---
name: propagation-model
description: "foF2/MUF model, antenna factor model, band freqs, known limitations"
metadata: 
  node_type: memory
  type: project
  originSessionId: 67f4cc15-833d-49d0-982f-a2dd3f24bb7c
---

## Ionospheric model (`propagation.py`)

Empirical F2-layer model — not ray-tracing (not VOACAP).

**Solar data sources (with fallback):**
1. `http://www.hamqsl.com/solarxml.php` — SFI, K-index, A-index, SSN, band conditions (HTTP only, not HTTPS)
2. NOAA SWPC JSON endpoints — fallback if hamqsl unreachable

**foF2 estimate (`_estimate_fof2`):**
```
base       = 0.01 * SFI + 3.5        # ~4.5 MHz at SFI=100
lat_factor = cos(lat)^0.4            # equatorial F2 is thicker
time_factor= 0.45 + 0.55 * max(0, cos(radians((local_hour - 14) * 15)))
foF2       = base * lat_factor * time_factor  (min 1.0)
```
Peaks at 14:00 local solar time. Night floor is 45% of daytime peak.

**MUF and strength per grid point:**
- Grid: 3° lat/lon steps, -75° to +78° lat, -180° to +177° lon
- Skip zone: points within 150 km excluded
- Multi-hop: foF2 evaluated at multiple path points; **weakest hop** sets path MUF:
  - < 2,000 km (1 hop): midpoint only; M-factor 3.2
  - 2,000–5,000 km (2 hops): 1/3 and 2/3 points; M-factor 3.7
  - > 5,000 km (3 hops): 1/4, 1/2, 3/4 points; M-factor 4.1
- Strength curve (probabilistic, not hard cutoff):
  - ratio = freq / MUF
  - ratio > 1.35 or < 0.45 → strength 0.0 (closed)
  - ratio 0.85–1.00 → strength 1.0 (prime FOT-to-MUF range)
  - ratio 1.00–1.35 → `((1.35 - ratio) / 0.35)^0.7` (above MUF, falling)
  - ratio 0.45–0.85 → `((ratio - 0.45) / 0.40)^1.5` (below FOT, rising)
- K-index penalty: `kp_penalty = max(0, 1 - (K/9) * 0.75)` applied to all paths

**Band frequencies (`app.py → BAND_FREQS`):**
```
80m: 3.500–4.000 MHz     60m: 5.330–5.404 MHz
40m: 7.000–7.300 MHz     20m: 14.00–14.35 MHz
17m: 18.07–18.17 MHz     15m: 21.00–21.45 MHz
10m: 28.00–29.70 MHz
```

**Cache:** 20m and 40m pre-warmed every 15 min by background thread. Other bands on-demand. Non-default antenna bypasses cache (`use_cache = antenna_type == 'vertical'`).

## Antenna model (`_antenna_factor` in `propagation.py`)

Applied multiplicatively to base ionospheric strength after kp_penalty. Normalized so λ/4 vertical = 1.0. All antennas assume resonance and average ground (σ ≈ 5 mS/m).

**Key helpers:**
- `_bearing(lat1,lon1,lat2,lon2)` → true bearing 0–360° clockwise from north
- `_takeoff_angle_deg(dist_km)` → geometric takeoff angle using 300 km F2 layer height; per-hop distance used for multi-hop paths; min 2°
- `_EL_NORM = 0.394` — normalization so dipole at 0.5λ broadside gives factor ≈ 1.30

**Vertical:**
- Omnidirectional; height_m ignored in UI (hidden when vertical selected)
- h < 0.15λ → factor scales from 0.3 (efficiency loss)
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
- Integer UTC hour — heatmap doesn't change within the same hour
- Arithmetic interpolation (not true great-circle) — small errors at high latitudes on long E-W paths
- No D-layer model (80m/40m real noise is higher than model suggests)
- No sporadic-E, greyline, or transequatorial propagation
