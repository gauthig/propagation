---
name: api-routes
description: "Flask routes (heatmap, antenna readout, auth, admin, tracking), DynamoDB design, IAM needs, external services"
metadata:
  node_type: memory
  type: project
  originSessionId: 01d8b071-b683-4806-9b45-7401f7b7e97b
  modified: 2026-09-27T18:16:35.635Z
---

## Routes (`app.py`, as of 2609.008)
| Route | Notes |
|---|---|
| `/` | page; `Cache-Control: max-age=600` → CloudFront edge-cached (use `?nocache=N` when testing) |
| `/robots.txt`, `/sitemap.xml`, `/BingSiteAuth.xml` | static, 24 h edge cache; robots disallows `/auth/ /admin/ /track/ /solar /heatmap/ /antenna/ /zip/` |
| `/heatmap/<band>` | `[[lat, lon, strength], …]`; params `lat lon antenna height_ft azimuth dipole_orient soil` |
| `/antenna/<band>` | readout JSON: antenna, soil {label, σ, εr}, gains [{elev, db}] @10°/20° best direction |
| `/solar`, `POST /solar/refresh` | solar indices (DynamoDB `current` row, refetch if >2 h); refresh stores `refreshed_by` |
| `/zip/<zip>` | zippopotam.us → {lat, lon, city, state}; 404 unknown, 502 network |
| `POST /track/visit|callsign|qth` | fire-and-forget visitor tracking keyed by callsign; always `{"ok": true}` |
| `/auth/me`, `POST /auth/login|register|logout` | cookie `hf_auth` = `CALLSIGN.token`, 30 days; PBKDF2-SHA256 260k iterations |
| `POST /auth/reset/request|confirm` | 6-char hex reset code emailed via SES (`SES_SENDER_EMAIL` env var) |
| `/admin/users`, `POST /admin/users/deactivate|reset-password` | require `admin` flag on the user row; deactivation clears the token |

- Bands: 80m 60m 40m 30m 20m 17m 15m 10m (`BAND_FREQS`; model uses band centre).
- Antenna params are parsed once in `_antenna_args()` (invalid → vertical / average soil / 30 ft).
- Heatmap LRU (`_heatmap_cache`, 32 entries) keyed on band, QTH (0.5°), antenna, height, azimuth,
  orientation, soil, SFI, K and UTC hour — every antenna is cached; maps can be ≤1 h old.
- Not logged in → the page locks QTH + antenna controls (band + greyline stay open).

## DynamoDB
- `hf_solar` (PK `record_id`): `current` row for O(1) `GetItem`; timestamped history rows carry
  `expire_at` and are deleted by DynamoDB TTL after 7 days (no Scan pruning any more).
- `hf_users` (PK `callsign`): tracking attrs (session_id, ip, first/last_seen, access_count,
  qth_*), plus auth attrs (password hash, auth_token/expires, email, active, admin, reset token).
- IAM (`terraform/iam.tf`): dynamodb Get/Put/Update/DeleteItem, Scan (only `/admin/users` scans
  now), BatchWriteItem; `ses:SendEmail`/`SendRawEmail`. History: a missing Scan permission once
  made every page load silently re-fetch solar data.

## External services
hamqsl.com XML (primary solar, HTTP only) → NOAA SWPC JSON fallback; zippopotam.us (ZIP);
jsDelivr (D3, world-atlas). Validation-only: KC2G API, wspr.live, NOAA F10.7/Kp (see [[propagation-model]]).

## CloudFront contract
Default behavior CachingDisabled; ordered CachingOptimized behaviors only for `/`, robots,
sitemap, BingSiteAuth, TTLs from Flask `Cache-Control`. NEVER a cache policy with Host in the
key (UseOriginCacheControlHeaders) — Host is forwarded and Lambda Function URLs 403 (prod outage
2026-07-18). Origin request policy AllViewerExceptHostHeader.
