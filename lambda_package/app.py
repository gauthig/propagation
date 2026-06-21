from flask import Flask, render_template, jsonify, request
import requests
import threading
import time
import base64
import sys
from io import BytesIO
from propagation import calculate_muf_map, get_solar_indices

app = Flask(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_LAT = 39.8   # Geographic center of contiguous US (central Kansas)
DEFAULT_LON = -98.6

REFRESH_INTERVAL = 900  # seconds

BAND_FREQS = {
    '80m': (3.500, 4.000),
    '60m': (5.330, 5.404),
    '40m': (7.000, 7.300),
    '20m': (14.000, 14.350),
    '17m': (18.068, 18.168),
    '15m': (21.000, 21.450),
    '10m': (28.000, 29.700),
}

# ── Server-side cache  (only 20m/40m are pre-warmed; others compute on demand) ─
_lock  = threading.Lock()
_cache = {
    'solar': None, 'last_update': None,
    'cache_lat': DEFAULT_LAT, 'cache_lon': DEFAULT_LON,
    '20m': None, '40m': None,
}


def _refresh_loop():
    while True:
        try:
            print("[refresh] fetching solar indices...")
            solar = get_solar_indices()
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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html',
                           default_lat=DEFAULT_LAT,
                           default_lon=DEFAULT_LON)


@app.route('/heatmap/<band>')
def heatmap(band):
    if band not in BAND_FREQS:
        return jsonify({'error': f'Invalid band. Valid: {list(BAND_FREQS.keys())}'}), 400

    try:
        req_lat = float(request.args.get('lat', DEFAULT_LAT))
        req_lon = float(request.args.get('lon', DEFAULT_LON))
    except (TypeError, ValueError):
        req_lat, req_lon = DEFAULT_LAT, DEFAULT_LON

    # Antenna parameters
    antenna_type  = request.args.get('antenna', 'vertical')
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

    # Non-default antenna always bypasses the pre-warmed vertical cache
    use_cache = (antenna_type == 'vertical')

    with _lock:
        solar     = _cache['solar']
        cache_lat = _cache['cache_lat']
        cache_lon = _cache['cache_lon']
        same_loc  = (abs(req_lat - cache_lat) < 0.5 and abs(req_lon - cache_lon) < 0.5)
        data      = _cache.get(band) if (same_loc and use_cache) else None

    if solar is None or data is None:
        solar = solar or get_solar_indices()
        freq_min, freq_max = BAND_FREQS[band]
        data = calculate_muf_map(req_lat, req_lon, freq_min, freq_max, solar,
                                 antenna_type=antenna_type, height_m=height_m,
                                 beam_azimuth=beam_azimuth, dipole_orient=dipole_orient)
        if same_loc and use_cache and band in ('20m', '40m'):
            with _lock:
                _cache['solar']       = solar
                _cache[band]          = data
                _cache['last_update'] = time.time()

    return jsonify(data)


@app.route('/solar')
def solar_data():
    try:
        with _lock:
            data   = dict(_cache['solar']) if _cache['solar'] else None
            uptime = _cache['last_update']
        if data is None:
            data   = get_solar_indices()
            uptime = time.time()
        data['last_update'] = uptime
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e), 'stale': True}), 500


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
        d = r.json()
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


def handler(event, context):
    """Minimal WSGI adapter for Lambda Function URLs (payload format v2.0)."""
    http      = event['requestContext']['http']
    path      = event.get('rawPath', '/')
    qs        = event.get('rawQueryString', '') or ''
    headers   = {k.lower(): v for k, v in (event.get('headers') or {}).items()}

    body = event.get('body') or ''
    body_bytes = base64.b64decode(body) if event.get('isBase64Encoded') else body.encode()

    environ = {
        'REQUEST_METHOD':  http['method'],
        'PATH_INFO':       path,
        'QUERY_STRING':    qs,
        'CONTENT_TYPE':    headers.get('content-type', ''),
        'CONTENT_LENGTH':  str(len(body_bytes)),
        'SERVER_NAME':     'lambda',
        'SERVER_PORT':     '443',
        'SERVER_PROTOCOL': 'HTTP/1.1',
        'wsgi.version':    (1, 0),
        'wsgi.url_scheme': 'https',
        'wsgi.input':      BytesIO(body_bytes),
        'wsgi.errors':     sys.stderr,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False,
        'wsgi.run_once':   False,
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
        'statusCode':     status_holder.get('code', 200),
        'headers':        resp_headers,
        'body':           base64.b64encode(body_out).decode() if is_binary else body_out.decode(),
        'isBase64Encoded': is_binary,
    }


if __name__ == '__main__':
    t = threading.Thread(target=_refresh_loop, daemon=True)
    t.start()
    app.run(debug=True, use_reloader=False)
