# HF Propagation Map

A real-time HF skywave propagation visualizer for amateur radio operators. Shows estimated band openness from your QTH to every point on the globe, driven by live solar indices and a physics-based ionospheric model.

![Stack](https://img.shields.io/badge/Python-3.10%2B-blue) ![Flask](https://img.shields.io/badge/Flask-3.x-green) ![AWS Lambda](https://img.shields.io/badge/Deploy-AWS%20Lambda-orange)

---

## What It Does

- Fetches live solar data (SFI, K-index, A-index, sunspot number) from hamqsl.com with a NOAA fallback
- Computes a global heatmap of propagation probability on the selected amateur band using a multi-hop F2 ionospheric model
- Renders the heatmap over a Winkel Tripel world map using D3.js and an HTML5 Canvas
- Supports three antenna models (vertical, dipole, hex beam) with height and orientation controls
- Lets you set your QTH by Maidenhead grid square, lat/lon, or US ZIP code
- Remembers your callsign and QTH across sessions via localStorage

---

## Project Structure

```
propagation/
├── app.py              # Flask app — routes, cache, Lambda handler
├── propagation.py      # Ionospheric model — foF2, MUF, antenna factors
├── templates/
│   └── index.html      # Single-page UI — D3 map, panel, all JavaScript
├── requirements.txt    # flask, requests
└── README.md
```

---

## Local Installation

### Prerequisites

- Python 3.10 or later
- pip

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/your-username/propagation.git
cd propagation

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the development server
python app.py
```

Open your browser to **http://127.0.0.1:5000**

You will see a Flask development-server warning in the terminal — that is expected and harmless for local use. The warning does not appear when deployed on Lambda.

The background thread pre-warms the 20m and 40m heatmap cache every 15 minutes. Other bands compute on demand when you select them.

---

## AWS Lambda Deployment

The app runs on Lambda behind a **Lambda Function URL** (no API Gateway required). A custom WSGI adapter in `app.py` translates Lambda Function URL payload v2.0 events directly into Flask WSGI calls — no third-party adapter library is needed.

### Package the app

Run this from the project root on Windows (PowerShell):

```powershell
$root = "C:\path\to\propagation"
$pkg  = "$root\lambda_package"

if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
New-Item -ItemType Directory -Path $pkg | Out-Null

pip install flask requests -t $pkg --quiet

Copy-Item "$root\app.py"         "$pkg\app.py"
Copy-Item "$root\propagation.py" "$pkg\propagation.py"
Copy-Item "$root\templates"      "$pkg\templates" -Recurse

$zip = "$root\lambda.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$pkg\*" -DestinationPath $zip

Write-Host "Done — $([math]::Round((Get-Item $zip).Length/1MB, 1)) MB"
```

On macOS / Linux (bash):

```bash
cd /path/to/propagation
rm -rf lambda_package
mkdir lambda_package

pip install flask requests -t lambda_package --quiet

cp app.py propagation.py lambda_package/
cp -r templates lambda_package/

cd lambda_package
zip -r ../lambda.zip .
cd ..
echo "Done — $(du -sh lambda.zip)"
```

### Deploy in the AWS Console

**1. Create the Lambda function**
- Open **Lambda** in the AWS Console → **Create function**
- Choose **Author from scratch**
- Function name: `hf-propagation` (or your choice)
- Runtime: **Python 3.12**
- Architecture: **x86_64**
- Click **Create function**

**2. Upload the zip**
- **Code** tab → **Upload from** → **.zip file**
- Select `lambda.zip` → **Save**

**3. Set the handler**
- **Code** tab → **Runtime settings** → **Edit**
- Handler: `app.handler`
- Click **Save**

**4. Set timeout and memory**
- **Configuration** tab → **General configuration** → **Edit**
- Memory: `512 MB`
- Timeout: `0 min 30 sec`
- Click **Save**

**5. Add a Function URL**
- **Configuration** tab → **Function URL** → **Create function URL**
- Auth type: **NONE** (public)
- Enable **Configure CORS** → Allow origin: `*`
- Click **Save**
- Copy the generated URL — that is your public app address

**6. Test**

Open the Function URL in a browser. The first request (cold start) takes 3–5 seconds while Lambda initializes and fetches solar data. Subsequent requests within the same warm instance are fast.

### Lambda sizing notes

| Setting | Value | Reason |
|---|---|---|
| Memory | 512 MB | The heatmap loop runs ~1 800 trig calls per request |
| Timeout | 30 s | Allows for slow solar data fetches from hamqsl.com |
| Runtime | Python 3.12 | Latest stable; no compiled extensions needed |

The in-memory solar cache in `propagation.py` (10-minute TTL) works within a warm Lambda instance. Cold starts simply fetch fresh data on the first request.

---

## How to Use

### Setting your QTH

Click **Set QTH** at the bottom of the panel. Three entry methods are available:

| Method | Input | Example |
|---|---|---|
| **Grid** | Maidenhead locator | `EM38ab` |
| **Lat/Lon** | Decimal degrees | `39.8`, `-98.6` |
| **ZIP** | US ZIP code | `90210` |

Your QTH is stored in localStorage and restored on the next visit.

### Selecting a band

Use the **Band** dropdown at the top of the panel. Available bands:

| Band | Frequency range |
|---|---|
| 80m | 3.5 – 4.0 MHz |
| 60m | 5.33 – 5.404 MHz |
| 40m | 7.0 – 7.3 MHz |
| 20m | 14.0 – 14.35 MHz |
| 17m | 18.068 – 18.168 MHz |
| 15m | 21.0 – 21.45 MHz |
| 10m | 28.0 – 29.7 MHz |

### Reading the heatmap

| Color | Meaning |
|---|---|
| **Bright green** | Band wide open — prime operating range (freq near MUF) |
| **Yellow** | Good conditions |
| **Orange** | Marginal — noisy but workable |
| **Deep red** | Very low probability |
| **No color** | Band closed to that area |

The dashed circle on the map marks the **skip zone** — the region too close for reliable skywave propagation on the selected band.

### Solar indices

The four cards in the panel update automatically. Hover over any card for an explanation of what the index means and how it affects propagation.

| Index | What it measures |
|---|---|
| **Solar Flux (SFI)** | 10.7 cm solar radio emission — primary driver of F2 layer ionization |
| **K-index** | Short-term geomagnetic disturbance (0–9); high values degrade HF |
| **A-index** | 24-hour geomagnetic activity average; > 30 indicates a storm |
| **Sunspot Number** | Proxy for solar cycle phase |

### Band conditions table

Shows Good / Fair / Poor for each band by day and night, sourced directly from hamqsl.com's calculated conditions.

### Antenna model

Check **Use antenna** to apply an antenna pattern to the heatmap. The baseline (unchecked) is an isotropic reference — all directions equally weighted.

| Antenna | What it models |
|---|---|
| **Vertical** | Omnidirectional. λ/4 height = optimal. Shorter reduces efficiency; much taller shifts the pattern upward and hurts DX. |
| **Dipole** | Figure-8 azimuth pattern. Set the wire orientation; the signal radiates broadside (90° to the wire). |
| **Hex Beam** | ~60° beamwidth, ~6 dBd forward gain, ~19 dB front-to-back. Valid on 20m–10m only. Set the beam azimuth. |

Height affects the elevation pattern via ground-reflection image theory — higher is not always better for DX.

---

## API Reference

The Flask backend exposes three endpoints, all returning JSON.

### `GET /heatmap/<band>`

Returns a heatmap array for the specified band.

**Path parameter:** `band` — one of `80m`, `60m`, `40m`, `20m`, `17m`, `15m`, `10m`

**Query parameters:**

| Parameter | Default | Description |
|---|---|---|
| `lat` | 39.8 | Station latitude |
| `lon` | -98.6 | Station longitude |
| `antenna` | `vertical` | `vertical`, `dipole`, or `hex_beam` |
| `height_ft` | 30 | Antenna height above ground in feet |
| `azimuth` | 0 | Hex beam pointing direction (degrees, 0 = north) |
| `dipole_orient` | 0 | Dipole wire azimuth (0 = N–S wire, 90 = E–W wire) |

**Response:** Array of `[lat, lon, strength]` triples where `strength` is 0.0–1.0.

```json
[[45, -90, 0.87], [45, -87, 0.91], ...]
```

### `GET /solar`

Returns the current solar indices.

```json
{
  "SFI": 152.0,
  "K-index": 2.0,
  "A-index": 8.0,
  "Sunspot Number": 112.0,
  "source": "hamqsl.com",
  "stale": false,
  "band_conditions": {
    "80m-40m_day": "Good",
    "20m-17m_day": "Fair"
  },
  "last_update": 1750000000.0
}
```

### `GET /zip/<zipcode>`

Geocodes a US ZIP code.

```json
{
  "zipcode": "90210",
  "city": "Beverly Hills",
  "state": "CA",
  "lat": 34.0901,
  "lon": -118.4065
}
```

---

## Propagation Model

The model is implemented entirely in `propagation.py` using the Python standard library (no numpy or scipy).

**foF2 estimation** (`_estimate_fof2`): Empirical formula relating solar flux (SFI) to critical frequency. Includes latitude taper (equatorial F2 is thicker) and a diurnal cosine curve peaking at 14:00 local time with a nighttime floor at 45% of the daytime peak. Consistent with ITU/CCIR median tables.

**MUF calculation**: `MUF = foF2 × M-factor`, where M-factor scales with path length (3.2 for single-hop, 3.7 for two-hop, 4.1 for three-hop paths). The weakest hop along the path limits the MUF.

**Probabilistic strength**: Rather than a hard MUF cutoff, the model uses a smooth curve:

- Below the LUF (0.45 × MUF): zero probability — D-layer absorption dominates
- LUF → FOT (0.45–0.85 × MUF): rising probability (noisy path)
- FOT → MUF (0.85–1.0 × MUF): 100% — optimal operating range
- MUF → 1.35 × MUF: falling probability — natural foF2 variability means the band can still open
- Above 1.35 × MUF: zero probability — genuinely closed

**Geomagnetic penalty**: `kp_penalty = 1.0 − (K-index / 9) × 0.75` — applied multiplicatively to all strengths.

**Antenna factor** (`_antenna_factor`): Multiplicative modifier normalized so a λ/4 vertical = 1.0. Computes takeoff angle geometrically from F2 layer height (300 km) and per-hop path length, then applies elevation and azimuth patterns for the selected antenna type and height.

---

## Dependencies

| Package | Purpose |
|---|---|
| `flask` | Web framework and template rendering |
| `requests` | HTTP client for solar data fetches |

All propagation math, XML parsing, and geometry use the Python standard library.

Frontend libraries loaded from CDN (no local install required):

| Library | Purpose |
|---|---|
| D3.js v7 | SVG world map, Winkel Tripel projection |
| d3-geo-projection v4 | Winkel Tripel support |
| TopoJSON client v3 | World geometry data |

---

## License

MIT
