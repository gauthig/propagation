from flask import Flask, render_template, jsonify, request
import requests
import threading
import time
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

    with _lock:
        solar     = _cache['solar']
        cache_lat = _cache['cache_lat']
        cache_lon = _cache['cache_lon']
        same_loc  = (abs(req_lat - cache_lat) < 0.5 and abs(req_lon - cache_lon) < 0.5)
        data      = _cache.get(band) if same_loc else None

    if solar is None or data is None:
        solar = solar or get_solar_indices()
        freq_min, freq_max = BAND_FREQS[band]
        data = calculate_muf_map(req_lat, req_lon, freq_min, freq_max, solar)
        if same_loc and band in ('20m', '40m'):
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


if __name__ == '__main__':
    t = threading.Thread(target=_refresh_loop, daemon=True)
    t.start()
    app.run(debug=True, use_reloader=False)
