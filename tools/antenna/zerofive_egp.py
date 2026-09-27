"""Generate antennas/zerofive_10_80.json — Zero Five 10–80m elevated ground plane vs the λ/4 baseline.

    .\\venv\\Scripts\\python.exe tools\\antenna\\zerofive_egp.py

For every band × base height (4–12 ft) × soil, the table holds the gain difference in dB, by
elevation angle, between:
  * the Zero Five 10–80m: 43 ft radiator, six 130-inch elevated radials, fed through a 4:1 UnUn
    and 100 ft of RG-213 to a tuner in the shack — modelled in NEC2++ over Sommerfeld ground, and
  * the app's baseline vertical: a resonant λ/4 ground-mounted vertical with a good radial field
    (10 Ω radial-system loss, ≈32 on-ground radials) and a matched feed.

NEC-2 cannot model a wire connected to real ground, so the baseline uses the MININEC-style method
EZNEC and K9YC use: currents over perfect ground, far field reflected off real ground (Fresnel
coefficient for vertical polarization), radial loss as a series resistance.

Needs the nec2++ command-line tool (https://tmolteno.github.io/necpp/) — set NEC2PP to its path.
"""
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'validate'))
from common import BANDS  # noqa: E402

NEC2PP = os.environ.get('NEC2PP', r'C:\Users\garre\tools\necpp\build\src\nec2++.exe')
OUT    = os.path.join(ROOT, 'antennas', 'zerofive_10_80.json')

C, FT, IN = 299.792458, 0.3048, 0.0254
AL_SIGMA  = 3.5e7                            # aluminium, S/m
HEIGHTS_FT = list(range(4, 13))              # base (radial) height above ground
ELEV_DEG   = list(range(1, 90))
SOILS = {                                    # relative permittivity, conductivity (S/m)
    'poor':    (5.0, 0.001),                 # desert, dry sand, rocky, urban
    'average': (13.0, 0.005),                # pasture, heavy clay
    'good':    (20.0, 0.03),                 # rich farmland, marshy
}
RADIATOR_FT, RADIAL_IN, N_RADIALS = 43.0, 130.0, 6
UNUN_RATIO, UNUN_LOSS_DB, COAX_FT = 4, 0.3, 100
REF_RADIAL_LOSS_OHM = 10.0


# ── NEC2++ model of the Zero Five ────────────────────────────────────────────

def run_nec(cards, workdir):
    deck = os.path.join(workdir, 'deck.nec')
    out  = os.path.join(workdir, 'deck.out')
    with open(deck, 'w', encoding='ascii') as f:
        f.write('\n'.join(cards) + '\n')
    subprocess.run([NEC2PP, '-i', deck, '-o', out], check=True, capture_output=True)
    return open(out, encoding='ascii', errors='replace').read()


def parse_nec(text):
    """Feedpoint impedance and azimuth-averaged total gain (dBi) at ELEV_DEG."""
    m = re.search(r'ANTENNA INPUT PARAMETERS.*?\n\s+1\s+\d+(?:\s+\S+){4}\s+(\S+)\s+(\S+)', text, re.S)
    z = complex(float(m.group(1)), float(m.group(2)))
    gains = {}
    for line in text.split('RADIATION PATTERNS')[1].splitlines():
        p = line.split()
        if len(p) >= 5 and re.fullmatch(r'-?\d+\.\d+', p[0]) and re.fullmatch(r'-?\d+\.\d+', p[1]):
            gains.setdefault(round(90 - float(p[0])), []).append(float(p[4]))
    g = np.array([10 * math.log10(np.mean([10 ** (v / 10) for v in gains[e]])) for e in ELEV_DEG])
    return z, g


def zerofive(f, soil, base_ft, workdir):
    er, sigma = SOILS[soil]
    hb, top = base_ft * FT, (base_ft + RADIATOR_FT) * FT
    cards = ['CM Zero Five 10-80m elevated ground plane', 'CE',
             f'GW 1 45 0 0 {hb:.4f} 0 0 {top:.4f} 0.0127']
    for i in range(N_RADIALS):
        a = 2 * math.pi * i / N_RADIALS
        x, y = RADIAL_IN * IN * math.cos(a), RADIAL_IN * IN * math.sin(a)
        cards.append(f'GW {i + 2} 11 0 0 {hb:.4f} {x:.4f} {y:.4f} {hb:.4f} 0.0048')
    cards += ['GE 0', f'LD 5 0 0 0 {AL_SIGMA}', f'GN 2 0 0 0 {er} {sigma}', 'EX 0 1 1 0 1.0 0',
              f'FR 0 1 0 0 {f} 0', f'RP 0 {len(ELEV_DEG)} 3 1000 {90 - ELEV_DEG[0]} 0 -1 30', 'EN']
    return parse_nec(run_nec(cards, workdir))


def feed_loss_db(z, f):
    """4:1 UnUn (plus core loss) then RG-213 at the resulting SWR; shack tuner treated as lossless."""
    z0  = 50.0 * UNUN_RATIO
    rho = abs((z - z0) / (z + z0))
    matched = (0.18 * math.sqrt(f) + 0.004 * f) * COAX_FT / 100          # RG-213 dB/100 ft fit
    a = 10 ** (matched / 10)
    return 10 * math.log10((a * a - rho * rho) / (a * (1 - rho * rho))) + UNUN_LOSS_DB, (1 + rho) / (1 - rho)


# ── MININEC-style λ/4 baseline ───────────────────────────────────────────────

def gamma_v(psi, er, sigma, f):
    ec = er - 1j * 60 * sigma * (C / f)
    root = np.sqrt(ec - np.cos(psi) ** 2)
    return (ec * np.sin(psi) - root) / (ec * np.sin(psi) + root)


def baseline(f, soil):
    """Gain (dBi) at ELEV_DEG of a resonant λ/4 ground-mounted vertical with 10 Ω radial loss."""
    er, sigma = SOILS[soil]
    k, H = 2 * np.pi * f / C, 0.25 * C / f
    z = np.linspace(0, H, 600)
    cur = np.sin(k * (H - z))

    def field(psi, gamma):
        s = np.sin(psi)[:, None]
        direct, reflected = np.exp(1j * k * z * s), gamma[:, None] * np.exp(-1j * k * z * s)
        integ = np.trapezoid(cur[None, :] * (direct + reflected), z, axis=1)
        return 30 * k * np.cos(psi) * np.abs(integ)

    fine = np.radians(np.linspace(0.01, 89.99, 4000))
    e_perf = field(fine, np.ones_like(fine))
    p_rad = 2 * np.pi / (240 * np.pi) * np.trapezoid(e_perf ** 2 * np.cos(fine), fine)   # time-average, W
    r_base = 2 * p_rad / np.sin(k * H) ** 2
    eff = r_base / (r_base + REF_RADIAL_LOSS_OHM)
    psi = np.radians(np.array(ELEV_DEG, float))
    e = field(psi, gamma_v(psi, er, sigma, f))
    return 10 * np.log10(e ** 2 / (240 * np.pi) * 4 * np.pi / p_rad * eff)


# ── Table ────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(NEC2PP):
        raise SystemExit(f'nec2++ not found at {NEC2PP} — build it and/or set NEC2PP')
    table = {
        'antenna': 'Zero Five 10-80m freestanding groundplane vertical with UnUn',
        'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'method': 'NEC2++ Sommerfeld ground for the Zero Five; MININEC-style lambda/4 baseline; '
                  'delta_db = Zero Five gain after UnUn+coax loss minus baseline gain, by elevation',
        'geometry': {'radiator_ft': RADIATOR_FT, 'radials': N_RADIALS, 'radial_in': RADIAL_IN},
        'feed': {'unun_ratio': UNUN_RATIO, 'unun_loss_db': UNUN_LOSS_DB, 'coax': f'{COAX_FT} ft RG-213',
                 'tuner': 'in shack, lossless'},
        'baseline': {'type': 'resonant lambda/4 ground-mounted', 'radial_loss_ohm': REF_RADIAL_LOSS_OHM},
        'soils': {k: {'er': v[0], 'sigma': v[1]} for k, v in SOILS.items()},
        'heights_ft': HEIGHTS_FT, 'elev_deg': ELEV_DEG, 'bands': {},
    }
    with tempfile.TemporaryDirectory() as work:
        for band, (freqs, _code) in BANDS.items():
            f = round((freqs[0] + freqs[1]) / 2, 4)
            entry = {'freq': f, 'delta_db': {}, 'feed': {}}
            for soil in SOILS:
                base = baseline(f, soil)
                rows, feed = [], []
                for hb in HEIGHTS_FT:
                    z, g = zerofive(f, soil, hb, work)
                    loss, swr = feed_loss_db(z, f)
                    rows.append([round(float(np.clip(d, -30, 20)), 1) for d in g - loss - base])
                    feed.append({'height_ft': hb, 'z': [round(z.real, 1), round(z.imag, 1)],
                                 'swr_unun': round(swr, 1), 'loss_db': round(loss, 2)})
                entry['delta_db'][soil] = rows
                entry['feed'][soil] = feed
            table['bands'][band] = entry
            mid = entry['delta_db']['average'][HEIGHTS_FT.index(7)]
            print(f'{band:4s} {f:7.3f} MHz  average soil, 7 ft base: '
                  f'{mid[9]:+5.1f} dB @10°, {mid[19]:+5.1f} dB @20°')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(table, f, separators=(',', ':'))
    print(f'wrote {os.path.relpath(OUT, ROOT)} ({os.path.getsize(OUT) / 1024:.0f} KB)')


if __name__ == '__main__':
    main()
