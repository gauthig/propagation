# Model validation tools

Checks `propagation.py` against real measurements, so calibration changes are backed by data
rather than eyeballing the map. These tools are dev-only: they are never packaged into
`lambda.zip`, and the downloaded data in `data/` is git-ignored.

| Script | What it does |
|---|---|
| `fetch_data.py` | Downloads a window (default 7 days) of ionosonde soundings, daily solar flux, Kp and WSPR reception |
| `ionosonde.py` | Scores the model's foF2 and MUF(3000) against the ionosondes, by station and by local time |
| `wspr.py` | Scores the whole heatmap against which WSPR receivers actually heard the home grid |
| `common.py` | Shared helpers: model loading (including old git versions), solar history, regions, AUC |

## Usage

Run these from the repo root with the project venv.

```powershell
.\venv\Scripts\python.exe tools\validate\fetch_data.py --days 7 --bands 20m,40m
.\venv\Scripts\python.exe tools\validate\ionosonde.py
.\venv\Scripts\python.exe tools\validate\wspr.py --band 20m
```

Compare a change against an earlier model version (any git ref), with a train/test split:

```powershell
.\venv\Scripts\python.exe tools\validate\wspr.py --band 20m --baseline HEAD~1 --split "2026-09-24 12:00"
```

Try a calibration without editing the model (`--set` overrides a module constant; repeatable):

```powershell
.\venv\Scripts\python.exe tools\validate\wspr.py --band 40m --set _AUR_DB=25 --set _AUR_WIDTH=5.0
.\venv\Scripts\python.exe tools\validate\ionosonde.py --set _NIGHT_FLOOR=0.40
```

Useful `fetch_data.py` options:
- `--grid` sets the WSPR "home" transmitters as a regex on the Maidenhead locator (default `^DM[01][234]`, Southern California).
- `--stations` takes a comma list of ionosonde URSI codes; the default is every station that reported in the last 6 hours.

To test from another QTH, change `--grid` when fetching and pass the matching `--qth lat,lon` to `wspr.py`.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Ionosonde foF2 / MUF(3000) | [KC2G](https://prop.kc2g.com/stations/) republishing [GIRO](https://giro.uml.edu/) | GIRO's own query service (`DIDBGetValues`) returned 404 in Sep 2026. KC2G's `history.json` takes KC2G's numeric station id, not the URSI code |
| WSPR reception | [wspr.live](https://wspr.live) public ClickHouse, table `wspr.rx` | Band codes: 3=80m, 7=40m, 10=30m, 14=20m, 18=17m, 21=15m, 28=10m |
| Daily F10.7 (SFI) | NOAA SWPC `f107_cm_flux.json` | Uses the 20:00 UTC "Noon" reading. SSN is estimated from F10.7 because there is no daily SSN feed |
| Kp | NOAA SWPC `noaa-planetary-k-index.json` | Only covers about the last 7 days, so keep `--days` ≤ 7 |

## Reading the numbers

- **foF2 bias / RMSE** (`ionosonde.py`): model minus measured, in MHz. Mid-latitude local-time bins matter most for a US QTH. `sigma(ln foF2)` is the day-to-day scatter, which the model's `_MUF_SIGMA` should roughly match.
- **AUC** (`wspr.py`): the chance that a receiver which heard the home grid got a higher predicted strength than one which didn't. 0.5 is a coin flip and 1.0 is perfect. Pooled AUC also rewards getting the relative levels between regions right.
- **Heard paths shown dark / not drawn**: openings the map missed. "Not drawn" uses the frontend's 0.12 display cutoff.
- **Reliability**: the hearing rate should rise steadily with predicted strength. Absolute rates depend on how many receivers there are and how sensitive they are, so compare the shape and compare within a region, not the raw percentages across regions.
- Regions with only a handful of hearings, such as Asia from Southern California, can't be judged either way.

## Reference results (Sep 20–27 2026, equinox, SFI 101–121, Kp ≤ 4.3)

| Check | Result |
|---|---|
| Ionosonde, 12 stations: mid-latitude foF2 RMSE | 1.26 MHz (2609.002) → 0.83 (2609.003 fit) |
| Ionosonde, 29 stations: mid-latitude bias by local time | −0.15 to −0.29 MHz |
| Ionosonde, 29 stations: tropics, evening | −1.8 to −2.3 MHz (known gap: equatorial anomaly under-modeled) |
| WSPR 20m from DM1x, held-out AUC | 0.784 (2609.002) → 0.857 (2609.004) |
| WSPR 40m from DM1x, held-out AUC | 0.789 (2609.003) → 0.887 (2609.004) |
| WSPR 20m heard paths shown dark | 16.1% → 5.0% |

All calibration so far comes from one week near an equinox from one QTH. Re-run these checks in other seasons, at higher solar flux, and during geomagnetic storms before trusting the constants there.
