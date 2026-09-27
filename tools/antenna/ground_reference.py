"""Generate antennas/vertical_lambda4.json — the reference antenna over every soil.

    .\\venv\\Scripts\\python.exe tools\\antenna\\ground_reference.py

The reference for every antenna factor in the app is a resonant λ/4 ground-mounted vertical with
a good radial field (10 Ω radial-system loss, ≈32 on-ground radials) over AVERAGE soil. This table
holds its gain (dBi) per band × soil × elevation, so the app can show how other soils change it.

NEC-2 cannot model a wire connected to real ground (a grounded λ/4 came out at 200 − j157 Ω), so
this uses the MININEC-style method EZNEC and K9YC use: currents over perfect ground, far field
reflected off real ground (Fresnel coefficient, vertical polarization), radial loss as a series
resistance. Checked: 5.16 dBi over perfect ground (theory 5.15); ≈ −1.1 dBi at 26° over average soil.
"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools', 'validate'))
from common import BANDS  # noqa: E402
from propagation import SOILS  # noqa: E402

OUT = os.path.join(ROOT, 'antennas', 'vertical_lambda4.json')
C = 299.792458
ELEV_DEG = list(range(1, 90))
REF_RADIAL_LOSS_OHM = 10.0


def gamma_v(psi, er, sigma, f):
    ec = er - 1j * 60 * sigma * (C / f)
    root = np.sqrt(ec - np.cos(psi) ** 2)
    return (ec * np.sin(psi) - root) / (ec * np.sin(psi) + root)


def reference_gain(f, soil):
    """Gain (dBi) at ELEV_DEG of a resonant λ/4 ground-mounted vertical with 10 Ω radial loss."""
    _, er, sigma, _ = SOILS[soil]
    k, H = 2 * np.pi * f / C, 0.25 * C / f
    z = np.linspace(0, H, 600)
    cur = np.sin(k * (H - z))

    def field(psi, gamma):
        s = np.sin(psi)[:, None]
        direct, reflected = np.exp(1j * k * z * s), gamma[:, None] * np.exp(-1j * k * z * s)
        return 30 * k * np.cos(psi) * np.abs(np.trapezoid(cur[None, :] * (direct + reflected), z, axis=1))

    fine = np.radians(np.linspace(0.01, 89.99, 4000))
    e_perf = field(fine, np.ones_like(fine))
    p_rad = 2 * np.pi / (240 * np.pi) * np.trapezoid(e_perf ** 2 * np.cos(fine), fine)   # time-average, W
    r_base = 2 * p_rad / np.sin(k * H) ** 2
    eff = r_base / (r_base + REF_RADIAL_LOSS_OHM)
    psi = np.radians(np.array(ELEV_DEG, float))
    e = field(psi, gamma_v(psi, er, sigma, f))
    return 10 * np.log10(e ** 2 / (240 * np.pi) * 4 * np.pi / p_rad * eff)


def main():
    table = {
        'antenna': 'resonant lambda/4 ground-mounted vertical, 10 ohm radial-system loss',
        'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'method': 'MININEC-style: currents over perfect ground, Fresnel reflection off real ground',
        'soils': {k: {'label': v[0], 'er': v[1], 'sigma': v[2]} for k, v in SOILS.items()},
        'elev_deg': ELEV_DEG, 'bands': {},
    }
    for band, (freqs, _code) in BANDS.items():
        f = round((freqs[0] + freqs[1]) / 2, 4)
        gains = {soil: [round(float(g), 2) for g in reference_gain(f, soil)] for soil in SOILS}
        table['bands'][band] = {'freq': f, 'gain_dbi': gains}
        g10 = '  '.join(f'{s} {gains[s][9]:+5.1f}' for s in SOILS)
        print(f'{band:4s} dBi @10°: {g10}')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(table, f, separators=(',', ':'))
    print(f'wrote {os.path.relpath(OUT, ROOT)} ({os.path.getsize(OUT) / 1024:.0f} KB)')


if __name__ == '__main__':
    main()
