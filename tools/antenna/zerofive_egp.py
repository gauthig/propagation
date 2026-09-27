"""Generate antennas/zerofive_10_80.json — Zero Five 10–80m elevated ground plane vs the reference.

    .\\venv\\Scripts\\python.exe tools\\antenna\\zerofive_egp.py

For every band × base height (4–12 ft) × soil, the table holds the gain difference in dB, by
elevation angle, between:
  * the Zero Five 10–80m over that soil: 43 ft radiator, six 130-inch elevated radials, fed
    through a 4:1 UnUn and 100 ft of RG-213 to a tuner in the shack — NEC2++, Sommerfeld ground, and
  * the app's fixed reference: a resonant λ/4 ground-mounted vertical with a good radial field
    over AVERAGE soil (ground_reference.py). Using one fixed reference makes soil an absolute
    effect — poor ground is worse for every antenna, not just relative to a vertical on it.

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
sys.path.insert(0, HERE)
from common import BANDS  # noqa: E402
from ground_reference import ELEV_DEG, SOILS, reference_gain  # noqa: E402

NEC2PP = os.environ.get('NEC2PP', r'C:\Users\garre\tools\necpp\build\src\nec2++.exe')
OUT    = os.path.join(ROOT, 'antennas', 'zerofive_10_80.json')

FT, IN     = 0.3048, 0.0254
AL_SIGMA   = 3.5e7                           # aluminium, S/m
HEIGHTS_FT = list(range(4, 13))              # base (radial) height above ground
RADIATOR_FT, RADIAL_IN, N_RADIALS = 43.0, 130.0, 6
UNUN_RATIO, UNUN_LOSS_DB, COAX_FT = 4, 0.3, 100


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
    _, er, sigma, _ = SOILS[soil]
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


# ── Table ────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(NEC2PP):
        raise SystemExit(f'nec2++ not found at {NEC2PP} — build it and/or set NEC2PP')
    table = {
        'antenna': 'Zero Five 10-80m freestanding groundplane vertical with UnUn',
        'generated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'method': 'NEC2++ Sommerfeld ground for the Zero Five over each soil; delta_db = its gain after '
                  'UnUn+coax loss minus the reference (lambda/4, 10 ohm radials, AVERAGE soil), by elevation',
        'geometry': {'radiator_ft': RADIATOR_FT, 'radials': N_RADIALS, 'radial_in': RADIAL_IN},
        'feed': {'unun_ratio': UNUN_RATIO, 'unun_loss_db': UNUN_LOSS_DB, 'coax': f'{COAX_FT} ft RG-213',
                 'tuner': 'in shack, lossless'},
        'reference': 'resonant lambda/4 ground-mounted, 10 ohm radial loss, average soil',
        'soils': {k: {'label': v[0], 'er': v[1], 'sigma': v[2]} for k, v in SOILS.items()},
        'heights_ft': HEIGHTS_FT, 'elev_deg': ELEV_DEG, 'bands': {},
    }
    with tempfile.TemporaryDirectory() as work:
        for band, (freqs, _code) in BANDS.items():
            f = round((freqs[0] + freqs[1]) / 2, 4)
            entry = {'freq': f, 'delta_db': {}, 'feed': {}}
            base = reference_gain(f, 'average')                  # one fixed reference for all soils
            for soil in SOILS:
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
