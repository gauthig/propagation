# HF Propagation Map

A real-time HF skywave propagation visualizer for amateur radio operators. Shows estimated band openness from your QTH to every point on the globe, driven by live solar indices and a physics-based ionospheric model.

![Stack](https://img.shields.io/badge/Python-3.10%2B-blue) ![Flask](https://img.shields.io/badge/Flask-3.x-green) ![AWS Lambda](https://img.shields.io/badge/Deploy-AWS%20Lambda-orange) ![DynamoDB](https://img.shields.io/badge/DB-DynamoDB-yellow)

---

## What It Does

- Fetches live solar data (SFI, K-index, A-index, sunspot number) from hamqsl.com with a NOAA fallback
- Caches solar data in DynamoDB — shared across all Lambda instances, auto-refreshed when over 2 hours old
- Computes a global heatmap of propagation probability on the selected amateur band using a multi-hop F2 ionospheric model
- Renders the heatmap over a Winkel Tripel world map using D3.js and an HTML5 Canvas
- Supports three antenna models (vertical, dipole, hex beam) with height and orientation controls
- Lets you set your QTH by Maidenhead grid square, lat/lon, or US ZIP code
- Tracks visitors in DynamoDB by callsign, session, IP, QTH, and access count
- Remembers your callsign and QTH across sessions via localStorage

---

## Project Structure

```
propagation/
├── app.py              # Flask app — routes, DynamoDB helpers, Lambda WSGI handler
├── propagation.py      # Ionospheric model — foF2, MUF, antenna factors
├── templates/
│   └── index.html      # Single-page UI — D3 map, panel, all JavaScript
├── requirements.txt    # flask, requests (boto3 is pre-installed in Lambda runtime)
└── README.md
```

---

## Local Installation

### Prerequisites

- Python 3.10 or later
- pip
- AWS credentials configured (`aws configure`) with DynamoDB access

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

# 3. Install dependencies (including boto3 for local DynamoDB access)
pip install -r requirements.txt
pip install boto3

# 4. Run the development server
python app.py
```

Open your browser to **http://127.0.0.1:5000**

The background thread pre-warms the 20m and 40m heatmap cache every 15 minutes and writes solar data to DynamoDB. You will see a Flask development-server warning — expected and harmless for local use.

### Local AWS credentials

The app reads and writes DynamoDB on every request. Your local IAM user needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
    "Resource": "*"
  }]
}
```

---

## AWS Setup

### DynamoDB tables

Create both tables in the AWS Console → DynamoDB → **Create table**:

**Table 1 — Solar cache**

| Setting | Value |
|---|---|
| Table name | `hf_solar` |
| Partition key | `record_id` (String) |

**Table 2 — Visitor tracking**

| Setting | Value |
|---|---|
| Table name | `hf_users` |
| Partition key | `session_id` (String) |

Use default settings for both. Wait for status **Active** before deploying.

### Lambda execution role

1. Lambda console → your function → **Configuration** → **Permissions** → click the role name
2. **Add permissions** → **Attach policies** → **Create inline policy** → JSON tab:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
    "Resource": "*"
  }]
}
```

3. Name it `hf-dynamodb-access` → **Create policy**

---

## AWS Lambda Deployment

A custom WSGI adapter in `app.py` translates Lambda Function URL payload v2.0 events directly into Flask WSGI calls — no third-party adapter library required.

### Package the app

**Windows (PowerShell):**

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

**macOS / Linux:**

```bash
cd /path/to/propagation
rm -rf lambda_package && mkdir lambda_package
pip install flask requests -t lambda_package --quiet
cp app.py propagation.py lambda_package/
cp -r templates lambda_package/
cd lambda_package && zip -r ../lambda.zip . && cd ..
```

> boto3 is NOT included in the zip — it is pre-installed in every Lambda Python runtime.

### Deploy in the AWS Console

1. **Create function** — Author from scratch, Python 3.12, x86_64
2. **Upload zip** — Code tab → Upload from → .zip file → select `lambda.zip` → Save
3. **Set handler** — Runtime settings → Edit → Handler: `app.handler` → Save
4. **Set timeout/memory** — Configuration → General configuration → Memory: `512 MB`, Timeout: `30 sec`
5. **Add Function URL** — Configuration → Function URL → Create → Auth type: NONE → Enable CORS → Allow origin: `*`, Allow methods: `*`, Allow headers: `content-type` → Save

Copy the generated Function URL — that is your public app address.

### Lambda sizing

| Setting | Value | Reason |
|---|---|---|
| Memory | 512 MB | Heatmap loop runs ~1,800 trig calls per request |
| Timeout | 30 s | Allows for slow solar data fetches from hamqsl.com |
| Runtime | Python 3.12 | Latest stable; no compiled extensions needed |

---

## How to Use

### Setting your QTH

Click **Set QTH** at the bottom of the panel. Three entry methods:

| Method | Input | Example |
|---|---|---|
| **Grid** | Maidenhead locator | `EM38ab` |
| **Lat/Lon** | Decimal degrees | `39.8`, `-98.6` |
| **ZIP** | US ZIP code | `90210` |

Your callsign and QTH are stored in browser localStorage and restored on every return visit.

### Selecting a band

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
| **Bright green** | Band wide open — prime operating range |
| **Yellow** | Good conditions |
| **Orange** | Marginal — noisy but workable |
| **Deep red** | Very low probability |
| **No color** | Band closed to that area |

The dashed circle marks the **skip zone** — too close for reliable skywave on the selected band.

### Antenna model

Check **Use antenna** to apply antenna pattern to the heatmap. Unchecked = baseline (no directional weighting).

| Antenna | Description |
|---|---|
| **Vertical** | Omnidirectional. λ/4 height optimal. |
| **Dipole** | Figure-8 pattern. Signal radiates broadside (90° to wire). |
| **Hex Beam** | ~60° beamwidth, ~6 dBd gain, ~19 dB F/B. 20m–10m only. |

### Refresh button

The **Refresh Now** button is only visible when your callsign is **WB0Z**. It forces a fresh solar data fetch from hamqsl.com regardless of cache age, and updates DynamoDB so all users see the new data.

---

## API Reference

### `GET /heatmap/<band>`

Returns heatmap array for the specified band.

**Query parameters:**

| Parameter | Default | Description |
|---|---|---|
| `lat` | 39.8 | Station latitude |
| `lon` | -98.6 | Station longitude |
| `antenna` | `vertical` | `vertical`, `dipole`, or `hex_beam` |
| `height_ft` | 30 | Antenna height in feet |
| `azimuth` | 0 | Hex beam direction (degrees) |
| `dipole_orient` | 0 | Dipole wire azimuth (0 = N–S, 90 = E–W) |

**Response:** `[[lat, lon, strength], ...]` — strength is 0.0–1.0.

### `GET /solar`

Returns current solar indices. Reads from DynamoDB cache; fetches fresh if cache is over 2 hours old.

```json
{
  "SFI": 152.0, "K-index": 2.0, "A-index": 8.0, "Sunspot Number": 112.0,
  "source": "hamqsl.com", "stale": false, "last_update": 1750000000.0,
  "band_conditions": { "80m-40m_day": "Good", "20m-17m_day": "Fair" }
}
```

### `POST /solar/refresh`

Forces a fresh solar fetch regardless of cache age. Updates DynamoDB. Returns same shape as `/solar`.

### `GET /zip/<zipcode>`

Geocodes a US ZIP code → `{zipcode, city, state, lat, lon}`.

### `POST /track/visit`

Body: `{"session_id": "<uuid>"}`. Increments `access_count`, updates `last_seen` and `ip_address`.

### `POST /track/callsign`

Body: `{"session_id": "<uuid>", "callsign": "W1AW"}`. Stores callsign on session row.

### `POST /track/qth`

Body: `{"session_id": "<uuid>", "lat": 39.8, "lon": -98.6, "method": "grid"}`. Stores QTH on session row.

---

## DynamoDB Schema

### `hf_solar`

| Attribute | Type | Description |
|---|---|---|
| `record_id` | String (PK) | Always `"current"` — single-row cache |
| `SFI` | Number | Solar flux index |
| `K-index` | Number | Geomagnetic K-index |
| `A-index` | Number | Geomagnetic A-index |
| `Sunspot Number` | Number | Daily sunspot count |
| `source` | String | `"hamqsl.com"` or `"NOAA"` |
| `band_conditions` | Map | Per-band day/night condition strings |
| `timestamp` | String | ISO 8601 UTC write time |
| `timestamp_epoch` | Number | Unix epoch — used for TTL comparison |

### `hf_users`

| Attribute | Type | Description |
|---|---|---|
| `session_id` | String (PK) | UUID from browser localStorage |
| `callsign` | String | Amateur radio callsign (if entered) |
| `ip_address` | String | Last seen IP address |
| `first_seen` | String | ISO 8601 UTC — set once, never overwritten |
| `last_seen` | String | ISO 8601 UTC — updated on every visit |
| `access_count` | Number | Atomically incremented on every page load |
| `qth_lat` | Number | Station latitude |
| `qth_lon` | Number | Station longitude |
| `qth_method` | String | `"grid"`, `"latlon"`, or `"zip"` |

---

## Propagation Model

Implemented in `propagation.py` using the Python standard library only.

**foF2** — empirical formula: `base = 0.01×SFI + 3.5`, tapered by latitude (cos^0.4) and a diurnal cosine peaking at 14:00 local time with a 45% nighttime floor.

**MUF** — `foF2 × M-factor` (3.2 single-hop / 3.7 two-hop / 4.1 three-hop). Limited by the weakest hop along the path.

**Strength curve** — probabilistic rather than hard cutoff:
- `< 0.45×MUF` → 0 (D-layer absorption)
- `0.45–0.85×MUF` → rising from 0 (below FOT, noisy)
- `0.85–1.0×MUF` → 1.0 (optimal range)
- `1.0–1.35×MUF` → falling (above nominal MUF, variability)
- `> 1.35×MUF` → 0 (closed)

**Geomagnetic penalty** — `1.0 − (K-index / 9) × 0.75` multiplied into all strengths.

**Antenna factor** — normalized so λ/4 vertical = 1.0. Takeoff angle computed from F2 layer height (300 km) and per-hop path length. Azimuth and elevation patterns applied for dipole and hex beam.

---

## Dependencies

**Backend** (in `requirements.txt`):

| Package | Purpose |
|---|---|
| `flask` | Web framework and template rendering |
| `requests` | HTTP client for solar data fetches |

**Lambda runtime** (pre-installed, not in zip):

| Package | Purpose |
|---|---|
| `boto3` | AWS SDK — DynamoDB read/write |

**Frontend** (CDN, no install):

| Library | Purpose |
|---|---|
| D3.js v7 | SVG world map, Winkel Tripel projection |
| d3-geo-projection v4 | Winkel Tripel support |
| TopoJSON client v3 | World geometry data |

---

## License

MIT
