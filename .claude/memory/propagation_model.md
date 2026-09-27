---
name: propagation-model
description: "foF2/MUF model, absorption, antenna factor model, band freqs, known limitations"
metadata: 
  node_type: memory
  type: project
  originSessionId: 67f4cc15-833d-49d0-982f-a2dd3f24bb7c
  modified: 2026-09-27T17:09:54.453Z
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

**foF2 at each hop midpoint (`_fof2`, 2609.003 — fitted to ionosondes, see below):**
```
eq    = cos(geomag lat)^8                        # _equatorial(lat_r, lon_d) — 2609.005 (was cos(geo lat)^24)
polar = clip((|lat| - 45) / 20, 0, 1)
peak  = (2.85 + 0.052*SFI) * (1 + 0.4*eq) * (1 - 0.2*polar)
cz(t) = cos(solar zenith) at midpoint, sun lagged 1.5 h (_F2_LAG_H)
lit   = clip((cz - sin(-20°)) / (1 - sin(-20°)), 0)   # _F2_RISE_ELEV: F2 lit before ground sunrise
level = max over tau=0..10 h of sqrt(lit(t-tau)) * exp(-tau / (2 + 4*eq))
foF2  = max(peak * (0.43 + 0.57*level) * (1 + 0.3*eq*exp(-½((LT-20)/2.5)²)), 1.0)   # pre-reversal term
```
2609.005 tropical re-fit (29 ionosondes): tropics RMSE 2.34→1.82 MHz; WSPR neutral. Pacific paths now
brighter than WSPR hearing supports → long multi-hop path loss is the next missing piece.
History: 2609.001 sqrt(cz) only (20m closed 20–22 PDT); 2609.002 added 3 h decay/floor 0.33.

**Greyline (2609.002):** if the QTH and the cell are both in twilight (sun elevation
−12°…+3°, `_TWILIGHT_CZ`) and both within ±60° lat (`_GREY_MAX_LAT` — polar regions sit in
twilight for days near equinox and flooded Antarctica with fake openings), MUF ×1.15 and
strength ×1.3. Heuristic. From DM14 it lights a faint (~0.23) 20m band along the far
dusk terminator (Middle East / Indian Ocean) at sunrise.
Declination from day-of-year, so season/latitude come from the zenith angle (no separate lat factor).
Path MUF = min over hops of foF2 × M. Time uses UTC hour+minute.

**Auroral absorption (2609.004):** at each hop ground point k/n (interior points ×2 crossings,
path ends ×1): `_AUR_DB · (f20/f)^0.5 · exp(−½((|maglat| − (72 − 2·Kp))/4)²)` added to loss_db.
`_mag_lat` = centred dipole, pole 80.8N 72.7W (Hudson Bay/S Greenland/Iceland ≈ 69°, London 53°,
DM14 41°, Anchorage 62°). Tuned on 20m WSPR (train Sep 20–24 12Z / test after): held-out AUC
0.814→0.859; 40m check 0.789→0.887. Freq exponent 0.5 chosen from 40m data over physical 2.
Re-run with the committed kit `tools/validate/` (fetch_data.py → ionosonde.py / wspr.py, with
`--baseline <git ref>`, `--split`, `--set NAME=VALUE`). On the wider 29-station set (Sep 27 fetch)
the tropics' evening foF2 is still −1.8 to −2.3 MHz low — the next calibration target.

**D-layer absorption (per hop, summed):**
`loss_dB = 677·(1+0.0037·SSN)·cos(χ)^0.75 / (f+1.4)² · M` (χ unlagged) →
strength × 10^(−loss/40). This is what fades 80m/40m on long daytime paths.

**Strength (2609.003):** `_p_open(r)` = Φ(−ln(f/MUF)/0.14) (tanh approximation of the
normal CDF — no scipy in Lambda): probability the band is open today given lognormal
day-to-day MUF scatter. Replaced the ad-hoc tail (≤1→1.0, 1–1.35 falling), which
overstated openness 2–5× and was the real cause of the old night-side "red wash".
Then × absorption × `kp_penalty` × greyline gain × antenna; server drops cells ≤ 0.03.
Frontend `drawHeatCanvas` skips < 0.12 and fades 0.12–0.35: ~9 blobs overlap per pixel,
so any per-blob alpha scale alone saturates the alpha cap and still washes the map.
`calculate_muf_map(..., now=None)` accepts an explicit time for validation runs.

**Ionosonde validation + fit (2026-09-27, applied in 2609.003):** 16,200 GIRO
soundings, 12 stations, Sep 20–27 2026, SFI 101–121 (equinox, one week only).
- Data: GIRO DIDBGetValues/ShowIonogramPage return 404 (Point Arguello PA836 has Sep 2026
  soundings listed but not servable; KC2G's PA836 feed stale since 2024-08). Working source:
  KC2G `https://prop.kc2g.com/api/stations.json` (latest per station, numeric `id`) and
  `https://prop.kc2g.com/api/history.json?station=<id>&days=7` → rows [time, cs, foF2, MUFD, hmF2].
  Daily SFI: NOAA `services.swpc.noaa.gov/json/f107_cm_flux.json` ("Noon" rows).
- Mid-lat daytime foF2 (08–16 LT) accurate: bias −0.27/−0.01 MHz. M(3000) fine: obs median 3.19 vs model 3.28.
- Mid-lat misses: dawn −1.7 MHz (rise too late), evening −1.2, night −0.8 (floor too low). RMSE 1.26.
- Tropics (<25°) −1.7 to −3.8 MHz (no equatorial anomaly / slow post-sunset decay). RMSE 3.11.
- Grid fit: scale 0.95 on peak, floor 0.43, lag 1.5 h, decay 2 h, F2 lit from sun −20°
  (layer sunlit before ground sunrise), equatorial boost 0.4·cos(lat)^24 on peak and +6 h decay
  → mid-lat RMSE 0.83 with ~0 bias every LT bin; tropics RMSE 1.70 (evening still −0.8..−1.1).
- Polar taper added after the fit: Gakona +1.38 → +0.27 MHz, Juliusruh +0.38 → −0.18 (cut 0.20 best).
- As applied: every station within ±0.7 MHz mean bias; MUF(3000) bias +0.1 MHz, RMSE 5.6 → 3.7.
- Day-to-day scatter σ(ln foF2) = 0.139 (10–90%: 0.85–1.18×, matches ITU deciles) → _MUF_SIGMA 0.14.
- VOACAP not run: needs installing ITS HF (Windows) or voacapl — user permission required.

**WSPR validation (2026-09-27):** wspr.live public ClickHouse (`https://db1.wspr.live/?query=`,
table `wspr.rx`, band=14). Unit = (hour, receiver active on 20m that hour, ≥300 km from DM14);
label = heard any SoCal tx (`tx_loc` matching `^DM[01][234]`). 106,411 receiver-hours, 14.3% heard.
- AUC 0.799 (2609.002) → 0.828 (2609.003); heard paths shown dark 16.1% → 4.6%.
- Fitted reliability by strength: ≤0.03 2.8% heard, 0.03–0.15 4.0%, 0.15–0.35 6.8%, 0.35–0.6 28.6%,
  ≥0.6 56% (monotonic; the old model's middle bins were not).
- Biggest fix: 03–06 PDT East Coast (their sunrise) — 24% heard; old model 0.00, new 0.21.
- Europe over-predicted by 2609.002/.003: 06–15 PDT mean strength ~0.3 but <1% of 44k European
  receiver-hours heard SoCal (polar route) — fixed by auroral absorption in 2609.004. Asia: too
  few hearings (~19) to judge. Real morning (06–09 PDT) Oceania opening confirmed (7.9% heard).

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

**Elevated GP — Zero Five 10–80m (`egp_zf80`, 2609.006):** `_egp_factor` reads
`antennas/zerofive_10_80.json` (NEC2++, see [[reference-nec2pp]]): delta dB vs the λ/4 baseline per
band × base height 4–12 ft × soil (poor 5/0.001, average 13/0.005, good 20/0.03) × elevation 1–89°,
incl. 4:1 UnUn + 100 ft RG-213 mismatch loss (user's setup), linearly interpolated → power ratio.
Avg soil, 7 ft, @10°/20°: 80m −7.4/−7.4, 60m −2.3/−2.4, 40m +0.2/−0.2, 30m +1.2/+0.1, 20m +1.8/−0.5,
17m +0.7/+1.0, 15m −1.2/+1.3, 10m −2.2/−5.2 (poor soil adds ~+1…+3 dB on 40–10m). Quirk: the app's
"Vertical" option is really a 30 ft vertical via `_vertical_factor` (UI hides its height), so it
isn't exactly the λ/4 reference the table is relative to.

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
- No sporadic-E or transequatorial propagation; greyline is a simple heuristic boost
- Calibration (foF2 fit, auroral term, display cutoff 0.12) comes from one week near the
  September 2026 equinox, SFI 101–121, Kp ≤ 4.3, one QTH (SoCal) — re-check in other seasons
- Frontend "Use antenna" gate: before 2609.002 the controls looked active on load while the
  box was unticked, so antenna changes were silently ignored. Now any antenna control
  auto-ticks it, settings persist in localStorage `hf_antenna`, and a saved hex beam opens on 20m
- No noise/SNR model — strength is a probability-like openness score
- Skip circle uses the median MUF; the map's 1.0–1.35 tail can show faint red inside it
