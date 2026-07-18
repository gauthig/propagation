import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import json
import logging
import time
import datetime

import numpy as np

log = logging.getLogger('hf.propagation')

# Cache
_solar_cache = None
_solar_cache_time = 0
CACHE_TTL = 600  # 10 minutes

# Network errors urllib can raise for a failed GET (timeout, DNS, conn reset…)
_NET_ERRORS = (urllib.error.URLError, TimeoutError, OSError)


def http_get(url, timeout=10, headers=None):
    """Minimal stdlib GET — replaces `requests`. Returns (status_code, body_bytes).

    HTTP error responses (4xx/5xx) are returned with their status and body
    rather than raised. Network-level failures raise (caller catches _NET_ERRORS).
    """
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get_solar_indices():
    """
    Fetch solar indices from hamqsl.com (primary) with NOAA as fallback.
    Returns cached data if a live fetch fails, marked stale=True.
    """
    global _solar_cache, _solar_cache_time

    if _solar_cache and (time.time() - _solar_cache_time) < CACHE_TTL:
        return _solar_cache

    data = _fetch_hamqsl()
    if data is None:
        data = _fetch_noaa()

    if data:
        data['stale'] = False
        _solar_cache = data
        _solar_cache_time = time.time()
        return data

    # All sources failed — return stale cache or safe defaults
    if _solar_cache:
        stale = dict(_solar_cache)
        stale['stale'] = True
        return stale

    log.warning('All solar data sources failed, using default values')
    return {
        'SFI': 100, 'K-index': 2, 'A-index': 10,
        'Sunspot Number': 50, 'source': 'defaults', 'stale': True,
        'band_conditions': {}
    }


def _fetch_hamqsl():
    """Fetch from hamqsl.com XML feed. Returns dict or None."""
    url = 'http://www.hamqsl.com/solarxml.php'
    try:
        status, content = http_get(url, timeout=10)
        log.debug('[hamqsl] HTTP %s, %d bytes', status, len(content))
        if status != 200 or not content:
            return None

        root = ET.fromstring(content)
        sd = root.find('.//solardata')
        if sd is None:
            log.warning('[hamqsl] <solardata> element not found')
            return None

        def txt(tag, default):
            val = sd.findtext(tag, default).strip()
            try:
                return float(val)
            except (ValueError, AttributeError):
                return float(default)

        # Parse per-band conditions (day/night) from <calculatedconditions>
        band_cond = {}
        for band_el in sd.findall('.//calculatedconditions/band'):
            name = band_el.get('name', '')
            tod = band_el.get('time', '')
            cond = (band_el.text or '').strip()
            band_cond[f'{name}_{tod}'] = cond

        data = {
            'SFI': txt('solarflux', '100'),
            'K-index': txt('kindex', '2'),
            'A-index': txt('aindex', '10'),
            'Sunspot Number': txt('sunspots', '50'),
            'source': 'hamqsl.com',
            'band_conditions': band_cond,
        }
        log.debug('[hamqsl] SFI=%s K=%s A=%s SSN=%s',
                  data['SFI'], data['K-index'], data['A-index'], data['Sunspot Number'])
        return data

    except ET.ParseError as e:
        log.warning('[hamqsl] XML parse error: %s', e)
    except _NET_ERRORS as e:
        log.warning('[hamqsl] Request error: %s', e)
    except Exception as e:
        log.warning('[hamqsl] Unexpected error: %s', e)
    return None


def _fetch_noaa():
    """Fetch from NOAA SWPC endpoints. Returns dict or None."""
    try:
        # K-index (3-hourly planetary)
        k_status, k_body = http_get(
            'https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json',
            timeout=10
        )
        log.debug('[NOAA-K] HTTP %s', k_status)
        k_index = 2.0
        a_index = 10.0
        if k_status == 200 and k_body:
            k_data = json.loads(k_body)
            if k_data:
                latest = k_data[-1]
                k_index = float(latest.get('Kp', 2))
                a_index = float(latest.get('a_running', 10))

        # Solar flux (monthly observed — take most recent with valid f10.7)
        sfi = 100.0
        ssn = 50.0
        sfi_status, sfi_body = http_get(
            'https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json',
            timeout=10
        )
        log.debug('[NOAA-SFI] HTTP %s', sfi_status)
        if sfi_status == 200 and sfi_body:
            sfi_data = json.loads(sfi_body)
            valid = [e for e in sfi_data if e.get('f10.7', -1) > 0]
            if valid:
                latest = valid[-1]
                sfi = float(latest['f10.7'])
                ssn = float(latest.get('observed_swpc_ssn', latest.get('ssn', 50)))

        data = {
            'SFI': sfi, 'K-index': k_index, 'A-index': a_index,
            'Sunspot Number': ssn, 'source': 'NOAA', 'band_conditions': {}
        }
        log.debug('[NOAA] SFI=%s K=%s A=%s SSN=%s', sfi, k_index, a_index, ssn)
        return data

    except _NET_ERRORS as e:
        log.warning('[NOAA] Request error: %s', e)
    except Exception as e:
        log.warning('[NOAA] Unexpected error: %s', e)
    return None


# ── Propagation modelling (numpy-vectorized over the whole grid) ───────────────

# Normalization constant: dipole at 0.5λ, broadside, 20° takeoff → el_factor ≈ 1.30 vs vertical.
# el_raw at that geometry = |sin(π × 0.5 × sin(20°))| ≈ 0.512 → EL_NORM = 0.512 / 1.30
_EL_NORM = 0.394

# Static 3° grid — fine enough for smooth heatmap rendering. Built once and reused
# across every request; meshgrids are pure geometry and don't depend on solar/QTH.
_LATS = np.arange(-75, 80, 3, dtype=float)
_LONS = np.arange(-180, 180, 3, dtype=float)
_LAT, _LON = np.meshgrid(_LATS, _LONS, indexing='ij')   # shape (52, 120)


def _vertical_factor(h_lam):
    """λ/4 vertical is azimuth-independent → a single scalar across the grid."""
    if h_lam < 0.15:
        return max(0.30, h_lam / 0.25)            # short: efficiency drops linearly
    if h_lam <= 0.35:
        return 1.0                                # λ/4 sweet spot
    return max(0.65, 1.0 - (h_lam - 0.35) * 0.5)  # too tall: pattern moves up


def calculate_muf_map(station_lat, station_lon, freq_min, freq_max, solar_indices=None,
                      antenna_type='vertical', height_m=10.0,
                      beam_azimuth=None, dipole_orient=0.0):
    """
    Return list of [lat, lon, strength] (strength 0–1) for heatmap rendering.
    strength = 1 → band wide open; 0 → band closed.

    Fully vectorized: every grid cell is evaluated in numpy array ops rather than
    a Python double loop, so a full ~6,200-cell map is computed in one pass.
    """
    if solar_indices is None:
        solar_indices = get_solar_indices()

    sfi = float(solar_indices.get('SFI', 100))
    k_index = float(solar_indices.get('K-index', 2))

    # Geomagnetic disturbance reduces propagation quality
    kp_penalty = max(0.0, 1.0 - (k_index / 9.0) * 0.75)

    freq_center = (freq_min + freq_max) / 2.0
    utc_hour = datetime.datetime.now(datetime.timezone.utc).hour

    LAT, LON = _LAT, _LON

    # ── Great-circle distance (haversine) station → every cell ────────────────
    la1 = np.radians(station_lat)
    lo1 = np.radians(station_lon)
    la2 = np.radians(LAT)
    lo2 = np.radians(LON)
    dlat = la2 - la1
    dlon = lo2 - lo1
    a = np.sin(dlat / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(dlon / 2) ** 2
    dist = 6371.0 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

    # ── Hop count / M-factor buckets by path length ───────────────────────────
    near = dist < 2000        # 1 hop
    mid  = (dist >= 2000) & (dist < 5000)   # 2 hops
    m_factor = np.select([near, mid], [3.2, 3.7], default=4.1)  # default = far (≥5000 km, 3 hops)

    # ── foF2 per hop midpoint; path MUF limited by the *weakest* (min) hop ────
    base = 0.01 * sfi + 3.5   # daytime peak scales ~linearly with SFI

    def fof2_at(f):
        lat_mid = station_lat + f * (LAT - station_lat)
        hour    = (utc_hour + (station_lon + f * (LON - station_lon)) / 15.0) % 24
        lat_factor  = np.cos(np.radians(np.minimum(np.abs(lat_mid), 75))) ** 0.4
        hour_angle  = np.radians((hour - 14) * 15)
        time_factor = 0.45 + 0.55 * np.maximum(0.0, np.cos(hour_angle))
        return np.maximum(base * lat_factor * time_factor, 1.0)

    # Reuse f=0.5 across near+far; compute each fraction once over the full grid.
    fof2_025, fof2_05, fof2_075 = fof2_at(0.25), fof2_at(0.5), fof2_at(0.75)
    fof2_13, fof2_23 = fof2_at(1 / 3), fof2_at(2 / 3)
    fof2 = np.select(
        [near, mid],
        [fof2_05, np.minimum(fof2_13, fof2_23)],
        default=np.minimum(np.minimum(fof2_025, fof2_05), fof2_075),
    )

    muf = fof2 * m_factor
    ratio = freq_center / muf

    # ── Probabilistic strength curve (see model notes) ────────────────────────
    #   <0.45 → below LUF (absorbed); 0.45–0.85 → noisy/rising; 0.85–1.00 → prime;
    #   1.00–1.35 → above MUF/falling; >1.35 → closed.  Clip power bases ≥0 so the
    #   inactive branches never produce NaN from a negative fractional power.
    above = np.power(np.clip((1.35 - ratio) / 0.35, 0, None), 0.7)
    below = np.power(np.clip((ratio - 0.45) / 0.40, 0, None), 1.5)
    strength = np.select(
        [(ratio > 1.35) | (ratio < 0.45), ratio > 1.0, ratio >= 0.85],
        [0.0, above, 1.0],
        default=below,
    )
    strength = np.clip(strength * kp_penalty, 0.0, 1.0)

    # ── Antenna factor (vectorized) ───────────────────────────────────────────
    lam_m = 300.0 / freq_center
    h_lam = max(0.01, height_m / lam_m)

    if antenna_type == 'vertical':
        ant_f = _vertical_factor(h_lam)   # scalar, broadcasts over the grid
    else:
        # True bearing station → cell
        x = np.sin(dlon) * np.cos(la2)
        y = np.cos(la1) * np.sin(la2) - np.sin(la1) * np.cos(la2) * np.cos(dlon)
        bearing = (np.degrees(np.arctan2(x, y)) + 360) % 360

        # F2 takeoff angle from per-hop geometry (300 km layer)
        hop = np.where(near, dist, np.where(mid, dist / 2.0, dist / 3.0))
        toa_rad = np.radians(np.maximum(2.0, np.degrees(np.arctan2(2.0 * 300.0, hop))))

        # Elevation pattern from ground-reflection image theory
        el_raw = np.maximum(np.abs(np.sin(np.pi * h_lam * np.sin(toa_rad))), 0.05)
        el_factor = el_raw / _EL_NORM

        if antenna_type == 'dipole':
            wire_az = float(dipole_orient) % 180   # wire axis = null; broadside = max
            angle_from_wire = np.abs(((bearing - wire_az + 180) % 360) - 180)
            az_factor = np.maximum(np.sin(np.radians(angle_from_wire)) ** 2, 0.02)
        else:  # hex_beam — 60° beamwidth, ~6 dBd gain, ~19 dB F/B
            baz = beam_azimuth if beam_azimuth is not None else 0.0
            angle_off = np.abs(((bearing - baz + 180) % 360) - 180)
            t = (angle_off - 30) / 60.0
            side = np.maximum(3.5 * np.cos(np.radians(t * 90)) ** 2, 0.12)
            az_factor = np.where(angle_off <= 30, 3.5,
                                 np.where(angle_off <= 90, side, 0.04))

        ant_f = az_factor * el_factor

    strength = np.clip(strength * ant_f, 0.0, 1.0)

    # ── Filter: skip too-close skywave cells and faint noise floor ────────────
    valid = (dist >= 150) & (strength > 0.03)
    out_lat = LAT[valid].astype(int)
    out_lon = LON[valid].astype(int)
    out_str = np.round(strength[valid], 3)
    heatmap = [[int(la), int(lo), float(st)]
               for la, lo, st in zip(out_lat, out_lon, out_str, strict=True)]

    log.debug('[propagation] %.3f MHz -> %d heatmap points', freq_center, len(heatmap))
    return heatmap
