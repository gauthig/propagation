"""Shared helpers for the model validation tools — see README.md in this folder."""
import ast
import datetime as dt
import inspect
import json
import os
import subprocess
import sys
import types
import urllib.parse
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
DATA = os.path.join(HERE, 'data')

DEFAULT_QTH  = (34.5, -117.0)      # DM14 (Apple Valley, CA)
DEFAULT_GRID = '^DM[01][234]'      # WSPR transmitters DM02–04 / DM12–14: Southern California

# Band name → (freq_min, freq_max) MHz, matching app.py BAND_FREQS, and wspr.live band code
BANDS = {
    '80m': ((3.5, 4.0), 3),       '60m': ((5.33, 5.404), 5),  '40m': ((7.0, 7.3), 7),
    '30m': ((10.1, 10.15), 10),   '20m': ((14.0, 14.35), 14), '17m': ((18.068, 18.168), 18),
    '15m': ((21.0, 21.45), 21),   '10m': ((28.0, 29.7), 28),
}

sys.path.insert(0, ROOT)
import propagation  # noqa: E402


# ── Data access ──────────────────────────────────────────────────────────────

def http_get(url, params=None, timeout=600):
    """GET → bytes (raises on network/HTTP errors — these tools should fail loudly)."""
    if params:
        url += '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def data_path(*parts):
    return os.path.join(DATA, *parts)


def require(path):
    if not os.path.exists(path):
        raise SystemExit(f'missing {os.path.relpath(path, ROOT)} — run tools/validate/fetch_data.py first')
    return path


# ── Model loading ────────────────────────────────────────────────────────────

def load_model(git_ref=None, overrides=()):
    """The propagation module from the working tree, or as of git_ref, with NAME=VALUE overrides.

    Overrides patch module constants (e.g. `_AUR_DB=25`, `_MAG_POLE=(80.5,-72.0)`), so a
    candidate calibration can be scored without editing propagation.py.
    """
    if git_ref:
        src = subprocess.run(['git', '-C', ROOT, 'show', f'{git_ref}:propagation.py'],
                             check=True, capture_output=True, text=True, encoding='utf-8').stdout
        mod = types.ModuleType(f'propagation@{git_ref}')
        exec(compile(src, f'{git_ref}:propagation.py', 'exec'), mod.__dict__)
    else:
        mod = propagation
    for item in overrides:
        name, sep, value = item.partition('=')
        if not sep or not hasattr(mod, name):
            raise SystemExit(f'bad override {item!r} — expected NAME=VALUE for an existing model constant')
        setattr(mod, name, ast.literal_eval(value))
    return mod


def run_map(mod, qth, band, solar, t):
    """calculate_muf_map at time t. Versions before 2609.003 had no `now=`, so freeze their clock."""
    if 'now' in inspect.signature(mod.calculate_muf_map).parameters:
        return mod.calculate_muf_map(*qth, *band, solar, now=t)

    class _Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return t

    real = mod.datetime
    mod.datetime = types.SimpleNamespace(datetime=_Frozen, timezone=dt.timezone)
    try:
        return mod.calculate_muf_map(*qth, *band, solar)
    finally:
        mod.datetime = real


# ── Solar / geomagnetic history ──────────────────────────────────────────────

class SolarHistory:
    """Daily observed F10.7 (NOAA "Noon" reading) and 3-hourly Kp from the fetched files."""

    def __init__(self):
        self.flux = {r['time_tag'][:10]: float(r['flux'])
                     for r in json.load(open(require(data_path('f107.json'))))
                     if r.get('reporting_schedule') == 'Noon' and r.get('flux')}
        self.kp = sorted(
            (dt.datetime.fromisoformat(r['time_tag']).replace(tzinfo=dt.timezone.utc), float(r['Kp']))
            for r in json.load(open(require(data_path('kp.json')))))

    def sfi(self, t):
        for back in range(5):
            day = (t.date() - dt.timedelta(days=back)).isoformat()
            if day in self.flux:
                return self.flux[day]
        return 100.0

    def k_index(self, t):
        return next((k for kt, k in reversed(self.kp) if kt <= t), 2.0)

    def solar(self, t):
        """Solar dict as calculate_muf_map expects. SSN is estimated from F10.7 (no daily SSN feed)."""
        sfi = self.sfi(t)
        return {'SFI': sfi, 'K-index': self.k_index(t), 'Sunspot Number': max(0.0, (sfi - 64.0) / 0.73)}


# ── Geography / scoring ──────────────────────────────────────────────────────

def gc_km(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def grid_cell(lat, lon):
    """Nearest cell of propagation.py's 3° heatmap grid."""
    return int(np.clip(round((lat + 75) / 3), 0, 51)) * 3 - 75, (int(round((lon + 180) / 3)) % 120) * 3 - 180


def region(lat, lon):
    if lat > 15 and -170 <= lon < -100:
        return 'N America west'
    if lat > 15 and -100 <= lon <= -50:
        return 'N America east'
    if lat <= 15 and -95 <= lon <= -30:
        return 'Caribbean/S America'
    if lat > 35 and -30 <= lon <= 45:
        return 'Europe'
    if -30 <= lon <= 60:
        return 'Africa/Mid-East'
    if lat > -10 and 60 < lon <= 150:
        return 'Asia'
    return 'Oceania/Pacific'


REGIONS = ['N America east', 'N America west', 'Caribbean/S America', 'Europe', 'Africa/Mid-East', 'Asia',
           'Oceania/Pacific']


def auc(score, label):
    """Probability a random positive outranks a random negative (ties count half); nan if one class."""
    score, label = np.asarray(score, float), np.asarray(label, bool)
    if label.all() or not label.any():
        return float('nan')
    order = np.argsort(score, kind='mergesort')
    _, inv, counts = np.unique(score[order], return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    ranks = np.empty(len(score))
    ranks[order] = ((ends - counts + 1 + ends) / 2.0)[inv]
    n1, n0 = label.sum(), (~label).sum()
    return float((ranks[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
