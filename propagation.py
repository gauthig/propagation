import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import json
import logging
import os
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

_R_EARTH      = 6371.0   # km
_F2_HEIGHT    = 300.0    # km — nominal F2 reflection height
_MAX_HOP_KM   = 3500.0   # longest practical single F2 hop; longer paths split into equal hops
_MIN_ELEV_DEG = 3.0      # lowest useful takeoff angle (terrain/ground losses below this)
# Diurnal foF2 constants below were fitted to 16,200 GIRO ionosonde soundings (12 stations,
# Sep 20–27 2026, SFI 101–121): mid-latitude RMSE 1.26 → 0.83 MHz. Re-check with tools/validate/.
_FOF2_A       = 2.85     # daytime foF2 peak = A + B·SFI  (≈ 8.1 MHz at SFI 100, mid-latitude)
_FOF2_B       = 0.052
_F2_LAG_H     = 1.5      # F2 ionization lags the sun → daily foF2 peak mid-afternoon
_F2_RISE_ELEV = -20.0    # sun elevation (deg) at which the F2 layer starts ionizing — at ~300 km it
                         # is sunlit well before ground sunrise, so foF2 climbs from first light
_NIGHT_FLOOR  = 0.43     # night-time foF2 as a fraction of the daytime peak
_DECAY_H      = 2.0      # post-sunset F2 decay time constant (h) at mid-latitudes
# Equatorial terms re-fitted on 29 ionosondes (Sep 20–27 2026) using *geomagnetic* latitude —
# the anomaly follows the magnetic equator (≈10° S of the geographic one over Brazil):
# tropics RMSE 2.34 → 1.82 MHz, evening bias −2.1 → −0.3 MHz, mid-latitudes unchanged.
_EQ_WIDTH_EXP = 8        # equatorial weight = cos(geomagnetic lat)^8 (~0.5 at 24°, ~0.1 at 41°)
_EQ_BOOST     = 0.4      # equatorial-anomaly lift on the peak: ×(1 + 0.4·weight)
_EQ_DECAY_H   = 4.0      # extra post-sunset decay time near the magnetic equator: +4·weight h
_EQ_EVENING   = 0.3      # pre-reversal enhancement: foF2 ×(1 + 0.3·weight) around 20:00 local …
_EQ_EVE_LT    = 20.0     # … centred here (local solar hour) …
_EQ_EVE_W     = 2.5      # … Gaussian half-width in hours
_POLAR_CUT    = 0.20     # high-latitude (trough/auroral) peak reduction, ramped in from 45° to 65° |lat|
_DECAY_LOOK_H = 10       # hours of look-back for the decay
_MUF_SIGMA    = 0.14     # day-to-day σ of ln(foF2) around the median (measured; 10–90 % = 0.85–1.18×)
_TWILIGHT_CZ  = (-0.21, 0.05)   # sun elevation −12°…+3° → greyline band
_GREY_MUF     = 1.15     # greyline MUF lift (ionospheric tilt along the terminator)
_GREY_GAIN    = 1.3      # greyline strength gain (little D-layer absorption at either end)
_GREY_MAX_LAT = 60.0     # polar regions sit in twilight for days near equinox — not a greyline
_GYRO_MHZ     = 1.4      # electron gyrofrequency term in the D-layer absorption formula
_MAG_POLE     = (80.8, -72.7)   # geomagnetic (dipole) north pole, deg — over the Canadian Arctic
# Auroral constants tuned on a week of 20m WSPR from SoCal (train 4 days / test 3 days):
# held-out AUC 0.814 → 0.859; US West Coast → Europe mean strength 0.17 → 0.01 (0.2 % heard).
_AUR_LAT0     = 72.0     # auroral-absorption zone centre, geomagnetic |lat| at Kp 0 …
_AUR_KP_SHIFT = 2.0      # … moving equatorward this many degrees per Kp unit (68° at Kp 2)
_AUR_WIDTH    = 4.0      # Gaussian half-width of the zone (deg)
_AUR_DB       = 20.0     # loss per D-layer crossing at the zone centre, at 20m …
_AUR_FREQ_EXP = 0.5      # … scaled by (f20/f)^0.5. 40m WSPR preferred this over pure-absorption
                         # (f20/f)^2 (held-out AUC 0.883 → 0.887; EU heard-but-dark 69 % → 21 %) —
                         # the term also stands in for less frequency-dependent auroral scatter
_ABS_SCALE_DB = 40.0     # absorption dB that cuts strength by 10× (strength ∝ 10^(-dB/40))

# Static 3° grid — fine enough for smooth heatmap rendering. Built once and reused
# across every request; meshgrids are pure geometry and don't depend on solar/QTH.
_LATS = np.arange(-75, 80, 3, dtype=float)
_LONS = np.arange(-180, 180, 3, dtype=float)
_LAT, _LON = np.meshgrid(_LATS, _LONS, indexing='ij')   # shape (52, 120)


def _solar_declination(now):
    """Sun declination in radians (cosine approximation, good to ~1°)."""
    doy = now.timetuple().tm_yday
    return np.radians(-23.44 * np.cos(2 * np.pi / 365.0 * (doy + 10)))


def _cos_zenith(lat_r, lon_d, utc_h, decl, lag_h=0.0):
    """cos(solar zenith angle) at lat (radians) / lon (degrees), optionally lagged by lag_h hours."""
    hour_angle = np.radians(((utc_h + lon_d / 15.0 - lag_h) % 24 - 12) * 15)
    return np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(hour_angle)


def _equatorial(lat_r, lon_d):
    """0–1 weight: ~1 at the geomagnetic equator, ~0.5 at 24°, ~0.1 at 41° geomagnetic latitude."""
    return np.cos(np.radians(_mag_lat(lat_r, lon_d))) ** _EQ_WIDTH_EXP


def _f2_level(lat_r, lon_d, utc_h, decl):
    """0–1 F2 ionization level from the lagged sun, decaying slowly (not instantly) after sunset."""
    s0    = np.sin(np.radians(_F2_RISE_ELEV))
    decay = _DECAY_H + _EQ_DECAY_H * _equatorial(lat_r, lon_d)
    level = np.zeros(np.shape(lat_r))
    for tau in range(_DECAY_LOOK_H + 1):
        cz    = _cos_zenith(lat_r, lon_d, utc_h - tau, decl, _F2_LAG_H)
        lit   = np.clip((cz - s0) / (1 - s0), 0.0, None)
        level = np.maximum(level, np.sqrt(lit) * np.exp(-tau / decay))
    return level


def _fof2(lat_r, lon_d, utc_h, decl, sfi):
    """Median foF2 (MHz) at a point — the fitted diurnal/latitude model."""
    eq    = _equatorial(lat_r, lon_d)
    polar = np.clip((np.abs(np.degrees(lat_r)) - 45.0) / 20.0, 0.0, 1.0)
    peak  = (_FOF2_A + _FOF2_B * sfi) * (1 + _EQ_BOOST * eq) * (1 - _POLAR_CUT * polar)
    fof2  = peak * (_NIGHT_FLOOR + (1 - _NIGHT_FLOOR) * _f2_level(lat_r, lon_d, utc_h, decl))
    # Pre-reversal enhancement: the equatorial anomaly intensifies for a few hours after sunset
    dt_eve = ((utc_h + lon_d / 15.0 - _EQ_EVE_LT + 12) % 24) - 12
    fof2   = fof2 * (1 + _EQ_EVENING * eq * np.exp(-0.5 * (dt_eve / _EQ_EVE_W) ** 2))
    return np.maximum(fof2, 1.0)


def _p_open(ratio):
    """Probability the band is open when freq/median-MUF = ratio, for lognormal MUF scatter _MUF_SIGMA.

    Normal CDF via the tanh approximation (error < 0.002) — numpy has no erfc and scipy
    isn't worth adding to the Lambda package for this.
    """
    x = -np.log(ratio) / _MUF_SIGMA
    return 0.5 * (1 + np.tanh(0.7978845608 * (x + 0.044715 * x ** 3)))


def _mag_lat(lat_r, lon_d):
    """Geomagnetic (centred-dipole) latitude in degrees."""
    pla, plo = np.radians(_MAG_POLE[0]), np.radians(_MAG_POLE[1])
    s = np.sin(lat_r) * np.sin(pla) + np.cos(lat_r) * np.cos(pla) * np.cos(np.radians(lon_d) - plo)
    return np.degrees(np.arcsin(np.clip(s, -1.0, 1.0)))


def _auroral_weight(lat_r, lon_d, k_index):
    """0–1 closeness to the auroral-absorption zone, which widens and moves equatorward with Kp."""
    centre = _AUR_LAT0 - _AUR_KP_SHIFT * k_index
    return np.exp(-0.5 * ((np.abs(_mag_lat(lat_r, lon_d)) - centre) / _AUR_WIDTH) ** 2)


def _hop_geometry(hop_km):
    """Curved-earth takeoff angle (radians) and MUF M-factor for one F2 hop of hop_km."""
    theta = hop_km / (2 * _R_EARTH)
    k     = _R_EARTH / (_R_EARTH + _F2_HEIGHT)
    elev  = np.maximum(np.arctan2(np.cos(theta) - k, np.sin(theta)), np.radians(_MIN_ELEV_DEG))
    sin_i = k * np.cos(elev)                      # sine of incidence angle at the layer
    return elev, 1.0 / np.sqrt(1.0 - sin_i ** 2)


def _gc_point(la1, lo1, la2, lo2, delta, frac):
    """Point at fraction frac along the great circle of angular length delta → (lat rad, lon deg)."""
    sin_d = np.maximum(np.sin(delta), 1e-9)
    a = np.sin((1 - frac) * delta) / sin_d
    b = np.sin(frac * delta) / sin_d
    x = a * np.cos(la1) * np.cos(lo1) + b * np.cos(la2) * np.cos(lo2)
    y = a * np.cos(la1) * np.sin(lo1) + b * np.cos(la2) * np.sin(lo2)
    z = a * np.sin(la1) + b * np.sin(la2)
    return np.arctan2(z, np.hypot(x, y)), np.degrees(np.arctan2(y, x))


# ── Antenna models ─────────────────────────────────────────────────────────────
# Every antenna factor is a power ratio against ONE fixed reference: a resonant λ/4 vertical
# with a good radial field (10 Ω) over AVERAGE soil, at the same takeoff angle. Soil therefore
# changes every antenna in absolute terms (poor ground is worse for all of them).

# key: (label, relative permittivity, conductivity S/m, examples) — ARRL Antenna Book ground table
SOILS = {
    'very_poor':  ('Very poor',  3.0,  0.001,  'city, industrial'),
    'poor':       ('Poor',       10.0, 0.002,  'desert, dry sand, rocky'),
    'average':    ('Average',    13.0, 0.005,  'pasture, heavy clay'),
    'good':       ('Good',       20.0, 0.0303, 'rich farmland, low hills'),
    'salt_water': ('Salt water', 81.0, 5.0,    'at the shoreline'),
}
_ANT_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'antennas')
_tables    = {}


def _table(name):
    """Lazily loaded NEC/reference table from antennas/ (generated by tools/antenna/)."""
    if name not in _tables:
        with open(os.path.join(_ANT_DIR, name), encoding='utf-8') as f:
            _tables[name] = json.load(f)
    return _tables[name]


def _soil(soil):
    return soil if soil in SOILS else 'average'


def _band_entry(table, freq_center):
    return min(table['bands'].values(), key=lambda b: abs(b['freq'] - freq_center))


def _vertical_soil_factor(freq_center, soil, elev_rad):
    """λ/4 vertical over `soil` vs over average soil — vertical polarization is soil-sensitive."""
    t = _table('vertical_lambda4.json')
    band = _band_entry(t, freq_center)
    db = np.asarray(band['gain_dbi'][_soil(soil)]) - np.asarray(band['gain_dbi']['average'])
    return 10 ** (np.interp(np.degrees(elev_rad), t['elev_deg'], db) / 10)


def _horizontal_el_raw(h_lam, elev_rad, soil, freq_center):
    """0–1 elevation factor of a horizontal antenna h_lam wavelengths up: direct wave plus the
    ground reflection (Fresnel, horizontal polarization). Over perfect ground this is
    |sin(2π·h/λ·sin ψ)|; real soil shifts the lobes slightly and fills the nulls."""
    _, er, sigma, _ = SOILS[_soil(soil)]
    ec    = er - 1j * 60.0 * sigma * (299.792458 / freq_center)
    s     = np.sin(elev_rad)
    root  = np.sqrt(ec - np.cos(elev_rad) ** 2)
    gamma = (s - root) / (s + root)
    return np.abs(1 + gamma * np.exp(-1j * 4 * np.pi * h_lam * s)) / 2


# Dipole/hex normalization: a 0.5λ-high dipole, broadside, at a 20° takeoff over average soil
# scores 1.30 against the vertical reference (the calibration point the app has always used).
_EL_NORM = float(_horizontal_el_raw(0.5, np.radians(20.0), 'average', 14.175)) / 1.30


def _egp_factor(freq_center, base_height_m, soil, elev_rad):
    """Zero Five 10–80m elevated GP vs the reference, per takeoff angle (NEC2++ table from
    tools/antenna/zerofive_egp.py, including the 4:1 UnUn and 100 ft RG-213 mismatch loss)."""
    t    = _table('zerofive_10_80.json')
    band = _band_entry(t, freq_center)
    rows = np.asarray(band['delta_db'][_soil(soil)], dtype=float)
    hts  = np.asarray(t['heights_ft'], dtype=float)
    h_ft = float(np.clip(base_height_m / 0.3048, hts[0], hts[-1]))
    i    = int(np.clip(np.searchsorted(hts, h_ft) - 1, 0, len(hts) - 2))
    w    = (h_ft - hts[i]) / (hts[i + 1] - hts[i])
    curve = rows[i] * (1 - w) + rows[i + 1] * w
    return 10 ** (np.interp(np.degrees(elev_rad), t['elev_deg'], curve) / 10)


def _antenna_factor(antenna_type, freq_center, height_m, soil, elev, bearing=None,
                    beam_azimuth=None, dipole_orient=0.0):
    """Power ratio vs the reference (λ/4 vertical, average soil) at takeoff angle `elev` (rad),
    toward `bearing` (deg, needed for dipole/hex). Scalars or numpy arrays."""
    if antenna_type == 'vertical':
        # A resonant λ/4 cut for the selected band with a good radial field — no height input
        return _vertical_soil_factor(freq_center, soil, elev)
    if antenna_type == 'egp_zf80':
        return _egp_factor(freq_center, height_m, soil, elev)   # height_m = base (radial) height

    h_lam  = max(0.01, height_m / (299.792458 / freq_center))
    el_factor = np.maximum(_horizontal_el_raw(h_lam, elev, soil, freq_center), 0.05) / _EL_NORM
    if antenna_type == 'dipole':
        wire_az = float(dipole_orient) % 180   # wire axis = null; broadside = max
        angle_from_wire = np.abs(((bearing - wire_az + 180) % 360) - 180)
        az_factor = np.maximum(np.sin(np.radians(angle_from_wire)) ** 2, 0.02)
    else:  # hex_beam — 60° beamwidth, ~6 dBd gain, ~19 dB F/B
        baz = beam_azimuth if beam_azimuth is not None else 0.0
        angle_off = np.abs(((bearing - baz + 180) % 360) - 180)
        t = (angle_off - 30) / 60.0
        side = np.maximum(3.5 * np.cos(np.radians(t * 90)) ** 2, 0.12)
        az_factor = np.where(angle_off <= 30, 3.5, np.where(angle_off <= 90, side, 0.04))
    return az_factor * el_factor


def antenna_gain_db(freq_min, freq_max, antenna_type, height_m=10.0, soil='average',
                    beam_azimuth=None, dipole_orient=0.0, elevations=(10, 20)):
    """dB vs the reference used in the map, in the antenna's best direction, at sample takeoff
    angles — for the on-screen readout. Dipole: broadside; hex beam: straight ahead."""
    f = (freq_min + freq_max) / 2.0
    best = {'dipole': (float(dipole_orient) % 180) + 90, 'hex_beam': beam_azimuth or 0.0}.get(antenna_type)
    out = []
    for e in elevations:
        fac = _antenna_factor(antenna_type, f, height_m, soil, np.radians(float(e)), best,
                              beam_azimuth, dipole_orient)
        out.append({'elev': e, 'db': round(float(10 * np.log10(max(float(fac), 1e-6))), 1)})
    return out


def calculate_muf_map(station_lat, station_lon, freq_min, freq_max, solar_indices=None,
                      antenna_type='vertical', height_m=10.0,
                      beam_azimuth=None, dipole_orient=0.0, now=None, soil='average'):
    """
    Return list of [lat, lon, strength] (strength 0–1) for heatmap rendering.
    strength = 1 → band wide open; 0 → band closed.

    Vectorized: every grid cell is evaluated in numpy array ops; the only Python
    loop is over hop index (≤6 for the longest great-circle paths).
    """
    if solar_indices is None:
        solar_indices = get_solar_indices()

    sfi     = float(solar_indices.get('SFI', 100))
    k_index = float(solar_indices.get('K-index', 2))
    ssn     = float(solar_indices.get('Sunspot Number', 50))

    # Geomagnetic disturbance reduces propagation quality
    kp_penalty = max(0.0, 1.0 - (k_index / 9.0) * 0.75)

    freq_center = (freq_min + freq_max) / 2.0
    now   = now or datetime.datetime.now(datetime.timezone.utc)   # explicit time for validation runs
    utc_h = now.hour + now.minute / 60.0
    decl  = _solar_declination(now)

    LAT, LON = _LAT, _LON

    # ── Great-circle distance (haversine) station → every cell ────────────────
    la1 = np.radians(station_lat)
    lo1 = np.radians(station_lon)
    la2 = np.radians(LAT)
    lo2 = np.radians(LON)
    dlat = la2 - la1
    dlon = lo2 - lo1
    a = np.sin(dlat / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(dlon / 2) ** 2
    dist  = _R_EARTH * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    delta = dist / _R_EARTH   # angular path length (radians)

    # ── Hop count and curved-earth hop geometry ───────────────────────────────
    n_hops = np.maximum(1, np.ceil(dist / _MAX_HOP_KM)).astype(int)
    elev, m_factor = _hop_geometry(dist / n_hops)

    # ── foF2 and D-layer absorption at each hop midpoint (great-circle path) ──
    # foF2 follows the sun at each reflection point (_fof2, fitted to ionosonde data);
    # the weakest hop limits the path MUF. Absorption follows the George–Bradley form
    # ∝ cos(χ)^0.75 / (f + fH)², per hop.
    abs_coeff = 677.0 * (1 + 0.0037 * ssn) / (freq_center + _GYRO_MHZ) ** 2
    fof2      = np.full(dist.shape, np.inf)
    loss_db   = np.zeros(dist.shape)
    for i in range(int(n_hops.max())):
        active     = i < n_hops
        frac       = np.minimum((2 * i + 1) / (2.0 * n_hops), 1.0)
        mlat, mlon = _gc_point(la1, lo1, la2, lo2, delta, frac)
        hop_fof2   = _fof2(mlat, mlon, utc_h, decl, sfi)
        fof2       = np.where(active, np.minimum(fof2, hop_fof2), fof2)
        cz_d       = np.maximum(_cos_zenith(mlat, mlon, utc_h, decl), 0.0)
        loss_db   += np.where(active, abs_coeff * cz_d ** 0.75 * m_factor, 0.0)

    # ── Auroral absorption at each hop's ground points (D-layer crossings) ────
    # Paths through the auroral zone lose signal that sun-driven D-layer absorption
    # misses — e.g. US West Coast ↔ Europe crosses it over Hudson Bay/Greenland.
    # Interior ground points are crossed twice (down, then up); the path ends once.
    if _AUR_DB > 0:
        aur_db = _AUR_DB * ((14.175 + _GYRO_MHZ) / (freq_center + _GYRO_MHZ)) ** _AUR_FREQ_EXP
        for k in range(int(n_hops.max()) + 1):
            on_path    = k <= n_hops
            glat, glon = _gc_point(la1, lo1, la2, lo2, delta, np.minimum(k / n_hops, 1.0))
            crossings  = np.where((k == 0) | (k == n_hops), 1.0, 2.0)
            loss_db   += np.where(on_path, aur_db * crossings * _auroral_weight(glat, glon, k_index), 0.0)

    # ── Greyline: both ends in twilight → higher MUF, little absorption ───────
    tw_lo, tw_hi = _TWILIGHT_CZ
    cz_qth  = _cos_zenith(la1, station_lon, utc_h, decl)
    cz_cell = _cos_zenith(la2, LON, utc_h, decl)
    grey    = ((tw_lo <= cz_qth <= tw_hi) & (abs(station_lat) <= _GREY_MAX_LAT)
               & (cz_cell >= tw_lo) & (cz_cell <= tw_hi) & (np.abs(LAT) <= _GREY_MAX_LAT))

    muf   = fof2 * m_factor * np.where(grey, _GREY_MUF, 1.0)
    ratio = freq_center / muf

    # ── Strength = probability the path's MUF exceeds the band today ─────────
    #   The model gives the *median* MUF; real foF2 scatters day to day (σ measured
    #   from ionosondes). At the median MUF the band is open half the time, at 1.2×
    #   ~10 %. How far *below* the MUF says nothing about signal level — low-band
    #   daytime loss comes from the absorption term instead.
    strength = _p_open(ratio)
    strength = strength * 10 ** (-loss_db / _ABS_SCALE_DB) * np.where(grey, _GREY_GAIN, 1.0)
    strength = np.clip(strength * kp_penalty, 0.0, 1.0)

    # ── Antenna factor (vectorized) at each cell's per-hop takeoff angle ──────
    bearing = None
    if antenna_type in ('dipole', 'hex_beam'):
        x = np.sin(dlon) * np.cos(la2)
        y = np.cos(la1) * np.sin(la2) - np.sin(la1) * np.cos(la2) * np.cos(dlon)
        bearing = (np.degrees(np.arctan2(x, y)) + 360) % 360      # true bearing station → cell
    ant_f = _antenna_factor(antenna_type, freq_center, height_m, soil, elev, bearing,
                            beam_azimuth, dipole_orient)

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
