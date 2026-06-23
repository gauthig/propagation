---
name: project-overview
description: "Architecture, purpose, tech stack, and deployment of the HF Propagation web app"
metadata: 
  node_type: memory
  type: project
  originSessionId: 01d8b071-b683-4806-9b45-7401f7b7e97b
---

Flask-based single-page web app that displays a real-time HF radio propagation heatmap on a world map.

**Why:** Ham radio operators need to know which bands are open and where they can make contacts from their current location (QTH).

**Production URL:** https://propagation.ggcloud.us

**Stack:**
- Backend: Flask (Python), `propagation.py` for ionospheric modelling, `requests` for solar data, `boto3` for DynamoDB
- Frontend: D3 v7 + d3-geo-projection v4 (Winkel Tripel projection) + topojson-client v3
- Database: AWS DynamoDB — two tables: `hf_solar` (solar cache + history) and `hf_users` (visitor tracking)
- Deployment: AWS Lambda (Function URL, Python 3.14) via a custom WSGI adapter in `app.py`
- CDN / Custom domain: CloudFront distribution in front of the Lambda Function URL
- World map data: `https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json`

**Key files:**
- `app.py` — Flask routes, DynamoDB helpers, Lambda WSGI handler, background refresh thread (local only)
- `propagation.py` — solar data fetch (hamqsl.com → NOAA fallback), MUF model, foF2 estimate
- `templates/index.html` — all HTML/CSS/JS in one file (no build step)
- `requirements.txt` — `flask`, `requests` only (boto3 is pre-installed in Lambda runtime)
- `LOCAL_INSTALL.md` — local dev setup guide
- `AWS_INSTALL.md` — Lambda + DynamoDB + CloudFront deployment guide

**DynamoDB tables:**
- `hf_solar` — PK: `record_id` (String)
  - `record_id = "current"` row: always present, updated on every refresh, used for O(1) `GetItem` freshness check
  - `record_id = "<timestamp>Z"` rows: one appended per refresh, oldest pruned when count > 100; includes `refreshed_by` (callsign or "auto")
- `hf_users` — PK: `callsign` (String). One row per callsign — stable cross-browser identity. `session_id` stored as attribute, not key. Anonymous visitors not tracked.

**IAM required actions:** `GetItem`, `PutItem`, `UpdateItem`, `Scan`, `BatchWriteItem`. Missing `Scan` causes every page load to silently re-fetch solar data (exception in `_get_solar_db` → always returns None).

**CloudFront / custom domain setup:**
- ACM wildcard cert `*.ggcloud.us` — must be in us-east-1 regardless of Lambda region
- CloudFront origin: Lambda Function URL (bare hostname, no https://)
- Origin request policy: **AllViewerExceptHostHeader** — critical, without this Lambda rejects the request (Host header mismatch)
- Cache policy: CachingDisabled
- Allowed methods: GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE (POST needed for tracking endpoints)
- Cloudflare DNS: CNAME `propagation` → CloudFront domain, proxy **OFF** (grey cloud / DNS only) — orange cloud conflicts with CloudFront SSL
- A bare CNAME directly to the Lambda Function URL does NOT work — Lambda validates the Host header

**How to run locally:** `.\venv\Scripts\python.exe app.py` (must use venv — system Python 3.14 has Flask/Werkzeug incompatibility). Requires boto3 in venv and valid AWS credentials.

**Lambda packaging:** `pip install flask requests -t lambda_package/`, copy source + templates, `Compress-Archive`. Handler: `app.handler`. No Mangum — custom WSGI adapter handles Lambda Function URL payload v2.0 directly.
