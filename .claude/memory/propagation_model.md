---
name: propagation-model
description: "Current ionospheric + antenna model (as of 2609.008), its calibration/validation evidence, and hard-won pitfalls"
metadata:
  node_type: memory
  type: project
  originSessionId: 67f4cc15-833d-49d0-982f-a2dd3f24bb7c
  modified: 2026-09-27T18:06:28.966Z
---

Empirical F2 model in `propagation.py` → `calculate_muf_map(..., now=None, soil='average')` — not
ray-tracing/VOACAP. Constants below are the code's; README "Propagation Model" has the prose.
Re-check anything here against the code before quoting it.

## Ionosphere (per hop midpoint)
- Grid 3°; cells <150 km dropped. Hops `n = ceil(d/3500 km)`, true great-circle midpoints
  (`_gc_point`); `_hop_geometry` = curved earth, 300 km layer, min takeoff 3° → takeoff `elev`
  (also drives antenna patterns) and M-factor (~1 short → ~3.37 at 3,500 km).
- `_fof2`: peak `(2.85+0.052·SFI)·(1+0.4·eq)·(1−0.2·polar)`; eq = cos(geomag lat)^8 (dipole pole
  80.8N 72.7W); polar ramps 45→65° |geo lat|. Level = max over 0–10 h look-back of
  √lit(t−τ)·e^(−τ/(2+4·eq)), lit from sun −20° (F2 sunlit before ground sunrise), 1.5 h lag.
  foF2 = peak·(0.43+0.57·level)·(1+0.3·eq·exp(−½((LT−20)/2.5)²)) — last term = pre-reversal lift.
- Path MUF = min over hops of foF2·M; greyline (both ends in sun −12…+3°, |lat|≤60°) ×1.15 MUF
  and ×1.3 strength (heuristic; the ±60° limit stops Antarctica's equinox twilight faking openings).
- Loss: D-layer `677(1+0.0037·SSN)cos^0.75χ/(f+1.4)²·M` per hop + auroral
  `20 dB·(f20/f)^0.5·exp(−½((|maglat|−(72−2Kp))/4)²)` per ground crossing → ×10^(−dB/40).
- Strength = `_p_open` = Φ(−ln(f/MUF)/0.14) (tanh CDF approx — no scipy in Lambda) × loss ×
  Kp penalty × antenna. Server drops ≤0.03; frontend hides <0.12 and fades 0.12–0.35 (≈9 blobs
  overlap per pixel, so a per-blob alpha fade alone still washes the map).

## Antennas — one fixed reference (2609.008)
`_antenna_factor()` = power ratio vs a λ/4 vertical with 10 Ω radials over AVERAGE soil, at the
cell's takeoff angle. Soils `SOILS`: very_poor 3/0.001, poor 10/0.002, average 13/0.005,
good 20/0.0303, salt_water 81/5 (εr / S/m, ARRL table). Soil is absolute (poor ground hurts all).
- Vertical: true resonant λ/4 for the band (user decision 2026-09-27), no height;
  `antennas/vertical_lambda4.json` G(soil)−G(avg). @10°: very poor −3.4 … salt +7.5 dB.
- Zero Five 10–80m (`egp_zf80`): NEC2++ table `antennas/zerofive_10_80.json`, band × base 4–12 ft
  × soil × elev 1–89°, incl. 4:1 UnUn + 100 ft RG-213 (user's setup), vs the avg-soil reference.
  Avg soil 7 ft @10°/20°: 80m −7.4/−7.4 (coax loss at SWR 60–100:1), 60m −2.3, 40m +0.2/−0.2,
  20m +1.8/−0.5, 10m −2.2/−5.2 (high-angle lobes). Base height only moves it 0.5–2 dB.
- Dipole / hex: el = |1+Γh·e^{−j4π(h/λ)sinψ}|/2 ÷ `_EL_NORM` (calibrated: 0.5λ broadside 20°
  avg → 1.30, the app's old heuristic level). Dipole az sin²; hex 3.5 fwd / 0.04 rear, 20–10m only.
- `antenna_gain_db()` + `/antenna/<band>` feed the top-center readout (dB @10°/20°, best direction).

## Validation evidence (Sep 20–27 2026, equinox, SFI 101–121, Kp ≤4.3, one QTH)
- Ionosondes via KC2G (GIRO's own DIDBGetValues was 404): mid-lat RMSE 1.26 → 0.83 MHz after
  the fit, no local-time bias; tropics 3.11 → 1.82 (29 stations) after the 2609.005 magnetic
  re-fit; day-to-day σ(ln foF2)=0.139 → `_MUF_SIGMA`; M(3000) obs 3.19 vs model 3.28.
- WSPR from DM1x (wspr.live): 20m AUC 0.797 (2609.002) → 0.865 (2609.004), 40m → 0.907; heard
  paths shown dark 16% → 4%; reliability monotonic (≤0.03 1.3% heard … ≥0.6 52%). Auroral term
  tuned with 4-day train / 3-day test. Europe from SoCal ≈0.2% heard (polar route).
- Re-run: `tools/validate/` (fetch_data → ionosonde.py / wspr.py, `--baseline <ref>`, `--split`,
  `--set NAME=VALUE`). Generators: `tools/antenna/` (see [[reference-nec2pp]]).

## Pitfalls learned (don't repeat)
- Pre-2609.001 foF2 was ~half of real (20m looked closed by day); old 1.35× tail overstated
  openness 2–5× and was the true cause of the night "red wash".
- Pre-2609.008 dipole formula sin(π·h/λ·sinψ) modeled every dipole at HALF its height.
- Pre-2609.008 Zero Five table was vs a vertical on the *same* soil → poor soil looked best.
- Skip circle (`estimateSkipKm` JS) must use hop-midpoint foF2 per bearing, and its constants
  mirror `propagation.py` (change both together).

Open items live in [[project-roadmap]].
