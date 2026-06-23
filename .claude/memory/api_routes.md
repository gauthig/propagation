---
name: api-routes
description: "All Flask routes, DynamoDB interactions, IAM requirements, and external services"
metadata: 
  node_type: memory
  type: project
  originSessionId: 01d8b071-b683-4806-9b45-7401f7b7e97b
---

## Flask routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Renders `index.html` with `default_lat`, `default_lon` |
| `/heatmap/<band>` | GET | Returns `[[lat, lon, strength], …]` heatmap array |
| `/solar` | GET | Returns solar indices — DynamoDB `GetItem('current')` first, fetches if >2 h old |
| `/solar/refresh` | POST | Forces a fresh solar fetch regardless of cache age (WB0Z-only button) |
| `/zip/<zipcode>` | GET | Looks up a US ZIP → `{lat, lon, city, state}` |
| `/track/visit` | POST | Upserts callsign row, increments access_count |
| `/track/callsign` | POST | Creates or updates callsign row; stores session_id as attribute |
| `/track/qth` | POST | Stores qth_lat, qth_lon, qth_method on callsign row |

### `/heatmap/<band>`
- Valid bands: `80m`, `60m`, `40m`, `20m`, `17m`, `15m`, `10m`
- Query params: `lat`, `lon`, `antenna` (vertical/dipole/hex_beam), `height_ft`, `azimuth` (hex beam), `dipole_orient`
- Solar data: reads from in-process cache → DynamoDB GetItem('current') → fetches fresh if both miss
- Heatmap cache: 20m/40m at default QTH pre-warmed in local dev; non-vertical antenna always bypasses

### `/solar` and `/solar/refresh`
- `/solar`: `GetItem(record_id='current')` from `hf_solar`; compares `timestamp_epoch` to now; fetches fresh if >2 h
- `/solar/refresh`: always fetches fresh; body `{callsign}` stored as `refreshed_by` in the new history row
- Both call `_update_solar_cache(data)` to warm the in-process `_cache` dict after a DynamoDB write

### Tracking endpoints — callsign is the identity
- **PK is `callsign`** (not session_id) — same row updated regardless of browser, IP, or device
- All three endpoints receive `callsign` in the JSON body; no-op if callsign is empty (anonymous users not tracked)
- `/track/visit` body: `{"callsign": "W1AW"}`
- `/track/callsign` body: `{"callsign": "W1AW", "session_id": "<uuid>"}` — session_id stored as attribute, not key
- `/track/qth` body: `{"callsign": "W1AW", "lat": 39.8, "lon": -98.6, "method": "grid"}`
- `ip_address` comes from `request.remote_addr` (Lambda WSGI adapter sets this from `event.requestContext.http.sourceIp`)
- `access_count` uses DynamoDB `ADD` — atomic increment
- All DynamoDB errors are caught and logged; endpoints always return `{"ok": true}` so JS fires-and-forgets

### `/zip/<zipcode>`
- Calls `https://api.zippopotam.us/us/{zipcode}` (free, no key needed)
- Returns 404 if ZIP not found, 502 on network error

## DynamoDB table design

### `hf_solar` (PK: `record_id` String)
Two kinds of rows:
- **`record_id = "current"`** — always present; updated on every refresh; used for fast O(1) `GetItem` freshness check on every page load
- **`record_id = "<timestamp>Z"`** (e.g. `2026-06-22T14:30:00.123456Z`) — one new row per refresh; oldest deleted when count exceeds 100
- Both kinds include: `SFI`, `K-index`, `A-index`, `Sunspot Number`, `source`, `band_conditions`, `timestamp`, `timestamp_epoch`, `refreshed_by`
- `refreshed_by`: callsign string or `"auto"` (background/startup fetch)
- Pruning uses `Scan` with `FilterExpression='record_id <> "current"'` then `batch_writer().delete_item()` on oldest rows

### `hf_users` (PK: `callsign` String)
- One row per callsign — the stable cross-browser identity
- `session_id`: most recent browser localStorage UUID (stored as attribute, not key)
- `ip_address`, `first_seen`, `last_seen`, `access_count`, `qth_lat`, `qth_lon`, `qth_method`
- Anonymous visitors (skipped callsign prompt) are NOT written to this table

## DynamoDB IAM requirements

Lambda execution role and local IAM user both need:
```json
{
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:Scan",
    "dynamodb:BatchWriteItem"
  ],
  "Resource": "*"
}
```
`Scan` is required for solar history pruning. `BatchWriteItem` is required for batch-deleting old history rows. Using `"Resource": "*"` avoids ARN-matching issues.

**Why not GetItem on read?** Old design used Scan to find the latest row — this failed silently (Scan was not in the IAM policy) and caused every page load to re-fetch solar data. Current design uses `GetItem('current')` on reads; Scan only runs on writes (pruning).

## External data sources

| Service | URL | Purpose |
|---|---|---|
| hamqsl.com | `http://www.hamqsl.com/solarxml.php` | Solar indices (primary) |
| NOAA K-index | `https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json` | Fallback |
| NOAA SFI | `https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json` | Fallback |
| zippopotam.us | `https://api.zippopotam.us/us/{zip}` | ZIP geocoding |
| world-atlas CDN | `https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json` | Map polygons |
