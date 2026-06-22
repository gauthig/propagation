from flask import Flask, render_template, jsonify, request
import requests
import threading
import time
import base64
import sys
import datetime
from decimal import Decimal
from io import BytesIO
from propagation import calculate_muf_map, get_solar_indices

import boto3

app = Flask(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
DEFAULT_LAT = 39.8
DEFAULT_LON = -98.6
REFRESH_INTERVAL   = 900   # seconds — local dev background thread
SOLAR_MAX_AGE_SECS = 7200  # 2 hours — DynamoDB cache TTL

BAND_FREQS = {
    '80m': (3.500, 4.000),
    '60m': (5.330, 5.404),
    '40m': (7.000, 7.300),
    '20m': (14.000, 14.350),
    '17m': (18.068, 18.168),
    '15m': (21.000, 21.450),
    '10m': (28.000, 29.700),
}

# ── DynamoDB ───────────────────────────────────────────────────────────────────
_dynamo      = boto3.resource('dynamodb')
_users_table = _dynamo.Table('hf_users')
_solar_table = _dynamo.Table('hf_solar')


def _to_dynamo(obj):
    """Recursively convert Python floats to Decimal for DynamoDB storage."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo(v) for v in obj]
    return obj


def _from_dynamo(obj):
    """Recursively convert DynamoDB Decimals back to Python floats."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_dynamo(v) for v in obj]
    return obj


# ── Solar DynamoDB cache ───────────────────────────────────────────────────────

def _get_solar_db():
    """Return cached solar data from DynamoDB if under 2 hours old, else None."""
    try:
        resp = _solar_table.get_item(Key={'record_id': 'current'})
        item = resp.get('Item')
        if not item:
            return None
        age = time.time() - float(item.get('timestamp_epoch', 0))
        if age > SOLAR_MAX_AGE_SECS:
            print(f"[dynamo] solar cache is {age/3600:.1f} h old — needs refresh")
            return None
        data = _from_dynamo(item)
        data.pop('record_id', None)
        data['last_update'] = data.pop('timestamp_epoch', time.time())
        print(f"[dynamo] solar cache hit — age {age/60:.0f} min")
        return data
    except Exception as e:
        print(f"[dynamo] solar read error: {e}")
        return None


def _put_solar_db(data):
    """Write solar data to DynamoDB hf_solar table."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        item = _to_dynamo({k: v for k, v in data.items() if k != 'last_update'})
        item['record_id']       = 'current'
        item['timestamp']       = now.isoformat()
        item['timestamp_epoch'] = Decimal(str(now.timestamp()))
        _solar_table.put_item(Item=item)
        print("[dynamo] solar cache written")
    except Exception as e:
        print(f"[dynamo] solar write error: {e}")


def _fetch_and_cache_solar():
    """Fetch fresh solar data from external APIs and store it in DynamoDB."""
    data = get_solar_indices()
    _put_solar_db(data)
    data['last_update'] = time.time()
    return data


def _update_solar_cache(data):
    """Warm the in-process cache after any solar fetch."""
    with _lock:
        _cache['solar']       = data
        _cache['last_update'] = data.get('last_update', time.time())


# ── User tracking ──────────────────────────────────────────────────────────────

def _upsert_user(session_id, ip, callsign=None):
    """Upsert a session row — increments access_count, updates last_seen and IP.
    Optionally sets callsign when provided."""
    if not session_id:
        return
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        set_expr = 'last_seen = :ts, ip_address = :ip, first_seen = if_not_exists(first_seen, :ts)'
        values   = {':ts': now, ':ip': ip, ':one': 1}
        if callsign:
            set_expr = f'callsign = :cs, {set_expr}'
            values[':cs'] = callsign
        _users_table.update_item(
            Key={'session_id': session_id},
            UpdateExpression=f'SET {set_expr} ADD access_count :one',
            ExpressionAttributeValues=values,
        )
    except Exception as e:
        print(f"[dynamo] upsert_user error: {e}")


def _track_visit(session_id, ip):
    _upsert_user(session_id, ip)


def _track_callsign(session_id, callsign, ip):
    if callsign:
        _upsert_user(session_id, ip, callsign=callsign)


def _track_qth(session_id, lat, lon, method):
    """Update QTH coordinates and entry method for a session."""
    if not session_id:
        return
    try:
        _users_table.update_item(
            Key={'session_id': session_id},
            UpdateExpression='SET qth_lat = :lat, qth_lon = :lon, qth_method = :m',
            ExpressionAttributeValues={
                ':lat': Decimal(str(lat)),
                ':lon': Decimal(str(lon)),
                ':m':   method,
            },
        )
    except Exception as e:
        print(f"[dynamo] track_qth error: {e}")


# ── In-process cache (warm Lambda instance / local dev) ───────────────────────
_lock  = threading.Lock()
_cache = {
    'solar': None, 'last_update': None,
    'cache_lat': DEFAULT_LAT, 'cache_lon': DEFAULT_LON,
    '20m': None, '40m': None,
}


def _refresh_loop():
    """Local dev background thread — pre-warms 20m/40m heatmap every 15 min."""
    while True:
        try:
            print("[refresh] fetching solar indices...")
            solar = _fetch_and_cache_solar()
            with _lock:
                lat = _cache['cache_lat']
                lon = _cache['cache_lon']
            print("[refresh] pre-computing 20m and 40m...")
            data_20m = calculate_muf_map(lat, lon, *BAND_FREQS['20m'], solar)
            data_40m = calculate_muf_map(lat, lon, *BAND_FREQS['40m'], solar)
            with _lock:
                _cache['solar']       = solar
                _cache['20m']         = data_20m
                _cache['40m']         = data_40m
                _cache['last_update'] = time.time()
            print(f"[refresh] done — 20m={len(data_20m)} pts, 40m={len(data_40m)} pts")
        except Exception as e:
            print(f"[refresh] ERROR: {e}")
            import traceback; traceback.print_exc()
        time.sleep(REFRESH_INTERVAL)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html',
                           default_lat=DEFAULT_LAT,
                           default_lon=DEFAULT_LON)


# ── Tracking endpoints ─────────────────────────────────────────────────────────

@app.route('/track/visit', methods=['POST'])
def track_visit():
    data = request.get_json(silent=True) or {}
    _track_visit(data.get('session_id', ''), request.remote_addr or '0.0.0.0')
    return jsonify({'ok': True})


@app.route('/track/callsign', methods=['POST'])
def track_callsign():
    data     = request.get_json(silent=True) or {}
    callsign = data.get('callsign', '').upper().strip()
    _track_callsign(data.get('session_id', ''), callsign, request.remote_addr or '0.0.0.0')
    return jsonify({'ok': True})


@app.route('/track/qth', methods=['POST'])
def track_qth():
    data = request.get_json(silent=True) or {}
    sid  = data.get('session_id', '')
    lat  = data.get('lat')
    lon  = data.get('lon')
    if sid and lat is not None and lon is not None:
        _track_qth(sid, float(lat), float(lon), data.get('method', ''))
    return jsonify({'ok': True})


# ── Solar ──────────────────────────────────────────────────────────────────────

@app.route('/solar')
def solar_data():
    try:
        data = _get_solar_db() or _fetch_and_cache_solar()
        _update_solar_cache(data)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e), 'stale': True}), 500


@app.route('/solar/refresh', methods=['POST'])
def solar_refresh():
    """Force a fresh solar fetch regardless of cache age. WB0Z-only button calls this."""
    try:
        data = _fetch_and_cache_solar()
        _update_solar_cache(data)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e), 'stale': True}), 500


# ── Heatmap ────────────────────────────────────────────────────────────────────

@app.route('/heatmap/<band>')
def heatmap(band):
    if band not in BAND_FREQS:
        return jsonify({'error': f'Invalid band. Valid: {list(BAND_FREQS.keys())}'}), 400

    try:
        req_lat = float(request.args.get('lat', DEFAULT_LAT))
        req_lon = float(request.args.get('lon', DEFAULT_LON))
    except (TypeError, ValueError):
        req_lat, req_lon = DEFAULT_LAT, DEFAULT_LON

    antenna_type = request.args.get('antenna', 'vertical')
    if antenna_type not in ('vertical', 'dipole', 'hex_beam'):
        antenna_type = 'vertical'
    try:
        height_ft = float(request.args.get('height_ft', 30))
    except (TypeError, ValueError):
        height_ft = 30.0
    height_m = height_ft * 0.3048

    beam_azimuth = None
    if antenna_type == 'hex_beam' and 'azimuth' in request.args:
        try:
            beam_azimuth = float(request.args.get('azimuth', 0)) % 360
        except (TypeError, ValueError):
            beam_azimuth = 0.0

    try:
        dipole_orient = float(request.args.get('dipole_orient', 0)) % 180
    except (TypeError, ValueError):
        dipole_orient = 0.0

    use_cache = (antenna_type == 'vertical')

    with _lock:
        solar     = _cache['solar']
        cache_lat = _cache['cache_lat']
        cache_lon = _cache['cache_lon']
        same_loc  = (abs(req_lat - cache_lat) < 0.5 and abs(req_lon - cache_lon) < 0.5)
        data      = _cache.get(band) if (same_loc and use_cache) else None

    if solar is None or data is None:
        # Pull solar from DynamoDB if not in process cache
        if solar is None:
            solar = _get_solar_db() or _fetch_and_cache_solar()
        freq_min, freq_max = BAND_FREQS[band]
        data = calculate_muf_map(req_lat, req_lon, freq_min, freq_max, solar,
                                 antenna_type=antenna_type, height_m=height_m,
                                 beam_azimuth=beam_azimuth, dipole_orient=dipole_orient)
        if same_loc and use_cache and band in ('20m', '40m'):
            _update_solar_cache(solar)
            with _lock:
                _cache[band] = data

    return jsonify(data)


# ── ZIP geocoding ──────────────────────────────────────────────────────────────

@app.route('/zip/<zipcode>')
def zip_lookup(zipcode):
    if not zipcode.isdigit() or len(zipcode) > 5:
        return jsonify({'error': 'Invalid ZIP code format'}), 400
    try:
        r = requests.get(
            f'https://api.zippopotam.us/us/{zipcode}',
            timeout=8,
            headers={'User-Agent': 'hf-propagation/1.0'},
        )
        if r.status_code == 404:
            return jsonify({'error': f'ZIP code {zipcode} not found'}), 404
        if not r.ok:
            return jsonify({'error': 'ZIP lookup service unavailable'}), 502
        d     = r.json()
        place = d['places'][0]
        return jsonify({
            'zipcode': zipcode,
            'city':    place['place name'],
            'state':   place['state abbreviation'],
            'lat':     float(place['latitude']),
            'lon':     float(place['longitude']),
        })
    except requests.RequestException as e:
        return jsonify({'error': f'Network error: {e}'}), 502
    except (KeyError, IndexError, ValueError):
        return jsonify({'error': 'Unexpected response from ZIP service'}), 500


# ── Lambda WSGI adapter ────────────────────────────────────────────────────────

def handler(event, context):
    """Minimal WSGI adapter for Lambda Function URLs (payload format v2.0)."""
    http    = event['requestContext']['http']
    path    = event.get('rawPath', '/')
    qs      = event.get('rawQueryString', '') or ''
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}

    body = event.get('body') or ''
    body_bytes = base64.b64decode(body) if event.get('isBase64Encoded') else body.encode()

    environ = {
        'REQUEST_METHOD':   http['method'],
        'PATH_INFO':        path,
        'QUERY_STRING':     qs,
        'CONTENT_TYPE':     headers.get('content-type', ''),
        'CONTENT_LENGTH':   str(len(body_bytes)),
        'REMOTE_ADDR':      http.get('sourceIp', '0.0.0.0'),
        'SERVER_NAME':      'lambda',
        'SERVER_PORT':      '443',
        'SERVER_PROTOCOL':  'HTTP/1.1',
        'wsgi.version':     (1, 0),
        'wsgi.url_scheme':  'https',
        'wsgi.input':       BytesIO(body_bytes),
        'wsgi.errors':      sys.stderr,
        'wsgi.multithread':  False,
        'wsgi.multiprocess': False,
        'wsgi.run_once':     False,
    }
    for k, v in headers.items():
        key = k.upper().replace('-', '_')
        if key not in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            environ[f'HTTP_{key}'] = v

    status_holder, resp_headers = {}, {}

    def start_response(status, response_headers, exc_info=None):
        status_holder['code'] = int(status.split(' ', 1)[0])
        resp_headers.update(dict(response_headers))

    body_out = b''.join(app(environ, start_response))
    ct = resp_headers.get('Content-Type', '')
    is_binary = not (ct.startswith('text/') or 'json' in ct)

    return {
        'statusCode':      status_holder.get('code', 200),
        'headers':         resp_headers,
        'body':            base64.b64encode(body_out).decode() if is_binary else body_out.decode(),
        'isBase64Encoded': is_binary,
    }


if __name__ == '__main__':
    t = threading.Thread(target=_refresh_loop, daemon=True)
    t.start()
    app.run(debug=True, use_reloader=False)
