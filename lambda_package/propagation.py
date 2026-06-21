import requests
import xml.etree.ElementTree as ET
import math
import time
import datetime

# Cache
_solar_cache = None
_solar_cache_time = 0
CACHE_TTL = 600  # 10 minutes


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

    print("WARNING: All solar data sources failed, using default values")
    return {
        'SFI': 100, 'K-index': 2, 'A-index': 10,
        'Sunspot Number': 50, 'source': 'defaults', 'stale': True,
        'band_conditions': {}
    }


def _fetch_hamqsl():
    """Fetch from hamqsl.com XML feed. Returns dict or None."""
    url = 'http://www.hamqsl.com/solarxml.php'
    try:
        resp = requests.get(url, timeout=10)
        print(f"[hamqsl] HTTP {resp.status_code}, {len(resp.content)} bytes")
        if resp.status_code != 200 or not resp.content:
            return None

        root = ET.fromstring(resp.content)
        sd = root.find('.//solardata')
        if sd is None:
            print("[hamqsl] <solardata> element not found")
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
            band_cond[f"{name}_{tod}"] = cond

        data = {
            'SFI': txt('solarflux', '100'),
            'K-index': txt('kindex', '2'),
            'A-index': txt('aindex', '10'),
            'Sunspot Number': txt('sunspots', '50'),
            'source': 'hamqsl.com',
            'band_conditions': band_cond,
        }
        print(f"[hamqsl] SFI={data['SFI']} K={data['K-index']} A={data['A-index']} SSN={data['Sunspot Number']}")
        return data

    except ET.ParseError as e:
        print(f"[hamqsl] XML parse error: {e}")
    except requests.RequestException as e:
        print(f"[hamqsl] Request error: {e}")
    except Exception as e:
        print(f"[hamqsl] Unexpected error: {e}")
    return None


def _fetch_noaa():
    """Fetch from NOAA SWPC endpoints. Returns dict or None."""
    try:
        # K-index (3-hourly planetary)
        k_resp = requests.get(
            'https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json',
            timeout=10
        )
        print(f"[NOAA-K] HTTP {k_resp.status_code}")
        k_index = 2.0
        a_index = 10.0
        if k_resp.status_code == 200 and k_resp.content:
            k_data = k_resp.json()
            if k_data:
                latest = k_data[-1]
                k_index = float(latest.get('Kp', 2))
                a_index = float(latest.get('a_running', 10))

        # Solar flux (monthly observed — take most recent with valid f10.7)
        sfi = 100.0
        ssn = 50.0
        sfi_resp = requests.get(
            'https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json',
            timeout=10
        )
        print(f"[NOAA-SFI] HTTP {sfi_resp.status_code}")
        if sfi_resp.status_code == 200 and sfi_resp.content:
            sfi_data = sfi_resp.json()
            valid = [e for e in sfi_data if e.get('f10.7', -1) > 0]
            if valid:
                latest = valid[-1]
                sfi = float(latest['f10.7'])
                ssn = float(latest.get('observed_swpc_ssn', latest.get('ssn', 50)))

        data = {
            'SFI': sfi, 'K-index': k_index, 'A-index': a_index,
            'Sunspot Number': ssn, 'source': 'NOAA', 'band_conditions': {}
        }
        print(f"[NOAA] SFI={sfi} K={k_index} A={a_index} SSN={ssn}")
        return data

    except requests.RequestException as e:
        print(f"[NOAA] Request error: {e}")
    except Exception as e:
        print(f"[NOAA] Unexpected error: {e}")
    return None


# ── Propagation modelling ─────────────────────────────────────────────────────

def _great_circle_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    a = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(lat1, lon1, lat2, lon2):
    """True bearing from (lat1,lon1) to (lat2,lon2), degrees clockwise from north."""
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lo2 - lo1
    x = math.sin(dlon) * math.cos(la2)
    y = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _takeoff_angle_deg(dist_km):
    """
    Estimated F2 takeoff angle (degrees above horizon) for a given path length.
    Uses geometric optics with a 300 km layer height and per-hop distance.
    """
    h_ion = 300.0
    hop = dist_km if dist_km < 2000 else (dist_km / 2.0 if dist_km < 5000 else dist_km / 3.0)
    return max(2.0, math.degrees(math.atan2(2.0 * h_ion, hop)))


# Normalization constant: dipole at 0.5λ, broadside, 20° takeoff → el_factor ≈ 1.30 vs vertical.
# el_raw at that geometry = |sin(π × 0.5 × sin(20°))| ≈ 0.512 → EL_NORM = 0.512 / 1.30
_EL_NORM = 0.394


def _antenna_factor(station_lat, station_lon, target_lat, target_lon,
                    dist_km, freq_mhz, antenna_type, height_m,
                    beam_azimuth=None, dipole_orient=0.0):
    """
    Multiplicative strength modifier for the chosen antenna aimed at (target_lat, target_lon).
    Normalized so a λ/4 vertical = 1.0 (the propagation model baseline).
    Assumes resonant antenna on the selected band, average ground (σ ≈ 5 mS/m).
    """
    lam_m = 300.0 / freq_mhz
    h_lam = max(0.01, height_m / lam_m)
    bearing = _bearing(station_lat, station_lon, target_lat, target_lon)
    toa_rad = math.radians(_takeoff_angle_deg(dist_km))

    if antenna_type == 'vertical':
        # Omnidirectional in azimuth. λ/4 ≈ optimal; shorter raises ground resistance,
        # much taller shifts radiation upward and hurts DX.
        if h_lam < 0.15:
            return max(0.30, h_lam / 0.25)       # short: efficiency drops linearly
        if h_lam <= 0.35:
            return 1.0                            # λ/4 sweet spot
        return max(0.65, 1.0 - (h_lam - 0.35) * 0.5)  # too tall: pattern moves up

    # ── Horizontal antenna: elevation from ground-reflection image-theory ──
    # F(θ) ≈ |sin(π · (h/λ) · sin θ)| for the main polarisation component
    el_raw = abs(math.sin(math.pi * h_lam * math.sin(toa_rad)))
    el_raw = max(el_raw, 0.05)    # real ground prevents a true null
    el_factor = el_raw / _EL_NORM

    # ── Azimuth pattern ────────────────────────────────────────────────────
    if antenna_type == 'dipole':
        # dipole_orient is the wire azimuth in degrees (0=N-S, 45=NE-SW, 90=E-W, 135=NW-SE).
        # Wire axis = null direction; broadside (90° to wire) is the radiation maximum.
        wire_az = float(dipole_orient) % 180   # dipole is symmetric, 0-179° covers all orientations
        angle_from_wire = abs(((bearing - wire_az + 180) % 360) - 180)
        az_factor = math.sin(math.radians(angle_from_wire)) ** 2
        az_factor = max(az_factor, 0.02)    # end-fire is never a perfect null

    else:  # hex_beam — 60° beamwidth, ~6 dBd gain, ~19 dB F/B
        baz = beam_azimuth if beam_azimuth is not None else 0.0
        angle_off = abs(((bearing - baz + 180) % 360) - 180)
        if angle_off <= 30:
            az_factor = 3.5                       # full main-beam gain
        elif angle_off <= 90:
            t = (angle_off - 30) / 60.0
            az_factor = 3.5 * math.cos(math.radians(t * 90)) ** 2
            az_factor = max(az_factor, 0.12)      # side-lobe floor
        else:
            az_factor = 0.04                      # rear: ≈ −19 dB vs forward

    return az_factor * el_factor


def _estimate_fof2(sfi, lat, local_hour):
    """
    Empirical estimate of critical frequency foF2 (MHz) based on solar flux.
    Formula tuned so that SFI≈100 gives foF2≈5 MHz daytime at mid-latitudes,
    consistent with ITU/CCIR tables and typical amateur-band openings.
    """
    # Daytime peak foF2 scales roughly linearly with SFI
    base = 0.01 * sfi + 3.5          # ~4.5 MHz at SFI=100, ~5.6 MHz at SFI=210
    # Latitude taper — equatorial F-layer is thicker
    lat_factor = math.cos(math.radians(min(abs(lat), 75))) ** 0.4
    # Diurnal: peak near 14 LT; floor ~45% of peak at night
    hour_angle = math.radians((local_hour - 14) * 15)
    time_factor = 0.45 + 0.55 * max(0.0, math.cos(hour_angle))
    return max(base * lat_factor * time_factor, 1.0)


def calculate_muf_map(station_lat, station_lon, freq_min, freq_max, solar_indices=None,
                      antenna_type='vertical', height_m=10.0,
                      beam_azimuth=None, dipole_orient=0.0):
    """
    Return list of [lat, lon, strength] (strength 0–1) for heatmap rendering.
    strength = 1 → band wide open; 0 → band closed.
    """
    if solar_indices is None:
        solar_indices = get_solar_indices()

    sfi = float(solar_indices.get('SFI', 100))
    k_index = float(solar_indices.get('K-index', 2))

    # Geomagnetic disturbance reduces propagation quality
    kp_penalty = max(0.0, 1.0 - (k_index / 9.0) * 0.75)

    freq_center = (freq_min + freq_max) / 2.0
    utc_hour = datetime.datetime.utcnow().hour

    heatmap = []
    # 3° grid — fine enough for smooth heatmap rendering
    lat_step, lon_step = 3, 3

    for lat in range(-75, 80, lat_step):
        for lon in range(-180, 180, lon_step):
            dist = _great_circle_km(station_lat, station_lon, lat, lon)
            if dist < 150:  # too close for skywave
                continue

            # M-factor and hop count scale with path length
            if dist < 2000:
                m_factor = 3.2
                fracs = [0.5]            # 1 hop  — evaluate at midpoint
            elif dist < 5000:
                m_factor = 3.7
                fracs = [1/3, 2/3]       # 2 hops — evaluate at each reflection
            else:
                m_factor = 4.1
                fracs = [0.25, 0.5, 0.75]  # 3 hops — evaluate at each reflection

            # The path MUF is limited by the *weakest* hop (minimum foF2).
            # Using a single midpoint caused distant targets (mid-Atlantic) to
            # appear more favourable than nearer ones (east coast) because the
            # midpoint of a longer path lands further east where local time is
            # closer to the ionospheric peak.
            fof2 = min(
                _estimate_fof2(
                    sfi,
                    station_lat + f * (lat - station_lat),
                    (utc_hour + (station_lon + f * (lon - station_lon)) / 15.0) % 24,
                )
                for f in fracs
            )

            muf = fof2 * m_factor          # Maximum Usable Frequency (median estimate)

            # Probabilistic strength curve — replaces the hard MUF cutoff.
            #
            # The nominal MUF is a *median*: the band is open ~50% of the time
            # exactly at the MUF.  Natural foF2 variability of ±15–20% means
            # paths up to ~35% above the nominal MUF still have real probability
            # of contact.  Conversely, paths below the FOT (0.85×MUF) are noisier
            # but workable.
            #
            # ratio = freq / MUF
            #   < 0.45  → below effective LUF — D-layer absorbs signal, zero chance
            #   0.45-0.85 → below FOT — noisy, rising probability
            #   0.85-1.00 → FOT to MUF — prime operating range, 100% reliable
            #   1.00-1.35 → above nominal MUF — scatter/variability, falling probability
            #   > 1.35  → genuinely closed, zero chance
            ratio = freq_center / muf

            if ratio > 1.35 or ratio < 0.45:
                strength = 0.0
            elif ratio > 1.0:
                # Above MUF: probability falls from ~1.0 at MUF to 0 at 1.35× MUF.
                # Exponent <1 keeps probability high near MUF, drops steeply past 1.2×.
                strength = ((1.35 - ratio) / 0.35) ** 0.7
            elif ratio >= 0.85:
                strength = 1.0             # FOT → MUF: optimal, full reliability
            else:
                # Below FOT: noisy path, rising from zero at LUF to 1.0 at FOT
                strength = ((ratio - 0.45) / 0.40) ** 1.5

            strength = max(0.0, min(1.0, strength * kp_penalty))

            if strength > 0.0:
                ant_f = _antenna_factor(
                    station_lat, station_lon, lat, lon, dist, freq_center,
                    antenna_type, height_m, beam_azimuth, dipole_orient,
                )
                strength = max(0.0, min(1.0, strength * ant_f))

            if strength > 0.03:            # lower floor so faint red still renders
                heatmap.append([lat, lon, round(strength, 3)])

    print(f"[propagation] {freq_center:.3f} MHz -> {len(heatmap)} heatmap points")
    return heatmap
