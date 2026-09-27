# Antenna model generators

Every antenna factor in the app is a power ratio against one fixed reference: a resonant λ/4 vertical with a good radial field (10 Ω) over **average** soil.
- `ground_reference.py` builds `antennas/vertical_lambda4.json`: that reference's gain for every band × soil × elevation (MININEC-style, see below). The app uses it for the Vertical option's soil effect, and the Zero Five table is expressed against it. Run it first, since `zerofive_egp.py` imports it.
- Soils come from `propagation.SOILS`, one list shared by the app and the generators.

`zerofive_egp.py` builds `antennas/zerofive_10_80.json`, the gain table behind the "Elevated GP (Zero Five 10–80m)" antenna option. It runs the [NEC2++](https://tmolteno.github.io/necpp/) antenna simulator for every band × base height (4–12 ft) × soil (poor/average/good). The table holds, for each elevation angle, the Zero Five's gain minus the app's baseline vertical, in dB. `propagation.py` interpolates it by base height and path takeoff angle. NEC is only needed to regenerate the table, never at run time.

```powershell
$env:PATH = "<WinLibs mingw64\bin>;$env:PATH"       # nec2++ was built with MinGW g++
$env:NEC2PP = "C:\Users\garre\tools\necpp\build\src\nec2++.exe"
.\venv\Scripts\python.exe tools\antenna\ground_reference.py
.\venv\Scripts\python.exe tools\antenna\zerofive_egp.py
```

Building NEC2++ (no pip wheels exist for Python 3.14, so the command-line tool is used instead of the Python bindings):

```powershell
git clone --depth 1 https://github.com/tmolteno/necpp.git C:\Users\garre\tools\necpp
cmake -S C:\Users\garre\tools\necpp -B C:\Users\garre\tools\necpp\build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=g++ -DNECPP_BUILD_TESTS=OFF -DBUILD_SHARED_LIBS=OFF -DNECPP_ENABLE_LTO=OFF
cmake --build C:\Users\garre\tools\necpp\build -j 8
```

## What is modeled

| | Zero Five 10–80m | Baseline vertical |
|---|---|---|
| Radiator | 43 ft aluminium (1" dia.) | resonant λ/4 |
| Ground system | 6 × 130" elevated radials at the base height | good radial field: 10 Ω loss (≈32 on-ground radials) |
| Ground model | NEC2++ Sommerfeld/Norton, per soil | MININEC-style: currents over perfect ground, Fresnel reflection off real ground |
| Feed | 4:1 UnUn (+0.3 dB), 100 ft RG-213 at the resulting SWR, tuner in shack (lossless) | matched |

The two methods differ because NEC-2 cannot model a wire *connected* to real ground. A grounded λ/4 came out at 200 − j157 Ω. The MININEC-style baseline is what EZNEC and K9YC use for ground-mounted verticals. It reproduces NEC's 5.15 dBi over perfect ground, and gives about −1.1 dBi at 26° over average soil with 10 Ω of radial loss.

Soils (`propagation.SOILS`, ARRL Antenna Book ground table): very poor εr 3 / σ 0.001 S/m (city, industrial); poor 10 / 0.002 (desert, dry sand, rocky); average 13 / 0.005 (pasture, clay); good 20 / 0.0303 (farmland, low hills); salt water 81 / 5.

Results agree with K9YC's EZNEC study of 43 ft verticals: weak on 80m (mostly feedline loss at an SWR of 60–100:1), good on 40–17m (5/8λ on 20m), and high-angle lobes on 12–10m.

To add another antenna, write a sibling generator that emits the same JSON shape. Then add an antenna type in `propagation.py` (`_egp_factor` shows the lookup), `app.py` (the allowed `antenna` values) and the page's antenna menu.
