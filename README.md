# HF Propagation Map

A real-time HF skywave propagation visualizer for amateur radio operators. Shows estimated band openness from your QTH to every point on the globe, driven by live solar indices and a physics-based ionospheric model.

![Stack](https://img.shields.io/badge/Python-3.10%2B-blue) ![Flask](https://img.shields.io/badge/Flask-3.x-green) ![AWS Lambda](https://img.shields.io/badge/Deploy-AWS%20Lambda-orange) ![DynamoDB](https://img.shields.io/badge/DB-DynamoDB-yellow)

---

## What It Does

- Fetches live solar data (SFI, K-index, A-index, sunspot number) from hamqsl.com with a NOAA fallback
- Caches solar data in DynamoDB — shared across all Lambda instances, auto-refreshed when over 2 hours old; keeps a 100-row history of every refresh
- Computes a global heatmap of propagation probability on the selected amateur band using a multi-hop F2 ionospheric model
- Renders the heatmap over a Winkel Tripel world map using D3.js and an HTML5 Canvas
- Supports three antenna models (vertical, dipole, hex beam) with height and orientation controls
- Lets you set your QTH by Maidenhead grid square, lat/lon, or US ZIP code
- Tracks visitors in DynamoDB by callsign (the stable cross-browser identity), IP, QTH, and access count
- Remembers your callsign and QTH across sessions via browser localStorage

---

## Project Structure

```
propagation/
├── app.py              # Flask app — routes, DynamoDB helpers, Lambda WSGI adapter
├── propagation.py      # Ionospheric model — foF2, MUF, antenna factors
├── templates/
│   └── index.html      # Single-page UI — D3 map, panel, all JavaScript
├── requirements.txt    # flask, requests  (boto3 is pre-installed in the Lambda runtime)
├── LOCAL_INSTALL.md    # Running the app on your own machine
└── AWS_INSTALL.md      # Deploying to AWS Lambda with DynamoDB and CloudFront
```

---

## Installation

| Environment | Guide |
|---|---|
| Local / development | [LOCAL\_INSTALL.md](LOCAL_INSTALL.md) |
| AWS Lambda + CloudFront | [AWS\_INSTALL.md](AWS_INSTALL.md) |

---

## How to Use

### Callsign

On first visit a prompt asks for your amateur radio callsign. Enter it and click **Save** — it is stored in browser localStorage and sent to the server to create or update your visitor record. Click **Skip** to continue anonymously (no visitor record is created). You can re-open the callsign dialog at any time by clicking the callsign badge in the panel header.

### Setting your QTH

Click **Set QTH** at the bottom of the panel. Three entry methods:

| Method | Input | Example |
|---|---|---|
| **Grid** | Maidenhead locator | `EM38ab` |
| **Lat/Lon** | Decimal degrees | `39.8`, `-98.6` |
| **ZIP** | US ZIP code | `90210` |

Your callsign and QTH are saved in browser localStorage and restored automatically on every return visit — including when you return from a different browser or device after re-entering your callsign.

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

### Solar indices panel

Displays Solar Flux Index, K-index, A-index, and Sunspot Number pulled from DynamoDB. The data is refreshed automatically when the cached value is more than 2 hours old. Hover each card for a plain-English explanation.

### Refresh button

The **Refresh Now** button is only shown when your callsign is **WB0Z**. It forces an immediate fetch from hamqsl.com regardless of cache age, writes a new row to the `hf_solar` history table (recording the callsign that triggered it), and updates the shared DynamoDB cache so all users see the new data.

---

## API Reference

### `GET /heatmap/<band>`

Returns heatmap data for the specified band.

**Query parameters:**

| Parameter | Default | Description |
|---|---|---|
| `lat` | 39.8 | Station latitude |
| `lon` | -98.6 | Station longitude |
| `antenna` | `vertical` | `vertical`, `dipole`, or `hex_beam` |
| `height_ft` | 30 | Antenna height in feet |
| `azimuth` | 0 | Hex beam pointing direction (degrees) |
| `dipole_orient` | 0 | Dipole wire azimuth (0 = N–S, 90 = E–W) |

**Response:** `[[lat, lon, strength], ...]` — strength is 0.0–1.0.

---

### `GET /solar`

Returns current solar indices. Reads from the DynamoDB `"current"` row; fetches fresh if over 2 hours old.

```json
{
  "SFI": 152.0,
  "K-index": 2.0,
  "A-index": 8.0,
  "Sunspot Number": 112.0,
  "source": "hamqsl.com",
  "last_update": 1750000000.0,
  "refreshed_by": "auto",
  "band_conditions": { "80m-40m_day": "Good", "20m-17m_day": "Fair" }
}
```

---

### `POST /solar/refresh`

Forces a fresh solar fetch regardless of cache age. Updates DynamoDB. Returns the same shape as `/GET /solar`.

Body: `{"callsign": "WB0Z"}` — stored in the history row as `refreshed_by`.

---

### `GET /zip/<zipcode>`

Geocodes a US ZIP code.

Response: `{"zipcode": "90210", "city": "Beverly Hills", "state": "CA", "lat": 34.09, "lon": -118.41}`

---

### `POST /track/visit`

Body: `{"callsign": "W1AW"}`. Upserts the visitor row, increments `access_count`, updates `last_seen` and `ip_address`. No-op if callsign is empty (anonymous visitors are not tracked).

### `POST /track/callsign`

Body: `{"callsign": "W1AW", "session_id": "<uuid>"}`. Creates or updates the callsign row; stores the current browser `session_id` as a reference attribute.

### `POST /track/qth`

Body: `{"callsign": "W1AW", "lat": 39.8, "lon": -98.6, "method": "grid"}`. Updates QTH fields on the callsign row.

---

## DynamoDB Schema

### `hf_solar`

Two kinds of rows coexist in this table:

**Fast-lookup row** — always present, updated on every refresh:

| Attribute | Type | Description |
|---|---|---|
| `record_id` | String (PK) | Always `"current"` |
| `SFI` | Number | Solar flux index |
| `K-index` | Number | Geomagnetic K-index |
| `A-index` | Number | Geomagnetic A-index |
| `Sunspot Number` | Number | Daily sunspot count |
| `source` | String | `"hamqsl.com"` or `"NOAA"` |
| `band_conditions` | Map | Per-band condition strings |
| `timestamp` | String | ISO 8601 UTC write time |
| `timestamp_epoch` | Number | Unix epoch — used for TTL comparison |
| `refreshed_by` | String | Callsign or `"auto"` |

**History rows** — one new row per refresh, oldest deleted when count exceeds 100:

Same attributes as above, but `record_id` is a UTC timestamp string (e.g. `2026-06-22T14:30:00.123456Z`).

---

### `hf_users`

| Attribute | Type | Description |
|---|---|---|
| `callsign` | String (PK) | Amateur callsign — stable cross-browser identity |
| `session_id` | String | Most recent browser localStorage UUID |
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

**Strength curve** — probabilistic rather than a hard cutoff:
- `< 0.45×MUF` → 0 (D-layer absorption)
- `0.45–0.85×MUF` → rising from 0 (below FOT, noisy)
- `0.85–1.0×MUF` → 1.0 (optimal range)
- `1.0–1.35×MUF` → falling (above nominal MUF, variability)
- `> 1.35×MUF` → 0 (closed)

**Geomagnetic penalty** — `1.0 − (K-index / 9) × 0.75` multiplied into all strengths.

**Antenna factor** — normalized so λ/4 vertical = 1.0. Takeoff angle computed from F2 layer height (300 km) and per-hop path length. Azimuth and elevation patterns applied for dipole and hex beam.

---

## Dependencies

**Backend** (`requirements.txt`):

| Package | Purpose |
|---|---|
| `flask` | Web framework and template rendering |
| `requests` | HTTP client for solar data fetches |

**Lambda runtime** (pre-installed — do not add to zip):

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
