"""Score the model's foF2 and MUF(3000) against fetched ionosonde soundings.

    .\\venv\\Scripts\\python.exe tools\\validate\\ionosonde.py
    .\\venv\\Scripts\\python.exe tools\\validate\\ionosonde.py --baseline HEAD~1 --set _NIGHT_FLOOR=0.40
"""
import argparse
import datetime as dt
import glob
import json
import os

import numpy as np

import common

LT_BINS  = [(0, 5, 'night 00-05'), (5, 8, 'dawn 05-08'), (8, 12, 'morning 08-12'),
            (12, 16, 'afternoon 12-16'), (16, 20, 'evening 16-20'), (20, 24, 'late 20-24')]
LAT_BANDS = [('mid-latitude 25-55', lambda a: (a >= 25) & (a <= 55)),
             ('low latitude <25', lambda a: a < 25), ('high latitude >55', lambda a: a > 55)]


def load_soundings(min_cs):
    """Rows of (code, name, lat, lon, time, foF2, MUF3000). KC2G cs: 0–100 scaling confidence, −1 unknown."""
    rows = []
    for path in sorted(glob.glob(common.require(common.data_path('ionosonde')) + os.sep + '*.json')):
        data = json.load(open(path))
        if not data or not data[0].get('history'):
            continue
        st = data[0]
        lon = st['longitude'] - 360 if st['longitude'] > 180 else st['longitude']
        for tstr, cs, fof2, mufd, _hmf2 in st['history']:
            if fof2 is None or (cs is not None and 0 <= cs < min_cs):
                continue
            t = dt.datetime.fromisoformat(tstr).replace(tzinfo=dt.timezone.utc)
            rows.append((st['code'], st['name'], st['latitude'], lon, t, fof2, mufd))
    if not rows:
        raise SystemExit('no ionosonde soundings found — run fetch_data.py')
    return rows


def model_fof2(mod, rows, solar):
    return np.array([float(mod._fof2(np.radians(np.array(lat)), np.array(lon), t.hour + t.minute / 60.0,
                                     mod._solar_declination(t), solar.sfi(t)))
                     for _c, _n, lat, lon, t, _f, _m in rows])


def summarize(label, obs, mod):
    return f'{label}  n {len(obs):5d}  obs {obs.mean():5.2f}  model {mod.mean():5.2f}  ' \
           f'bias {np.mean(mod - obs):+5.2f}  RMSE {np.sqrt(np.mean((mod - obs) ** 2)):4.2f}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--min-cs', type=float, default=50, help='drop soundings scaled with lower confidence')
    ap.add_argument('--baseline', help='git ref to compare against (e.g. HEAD~1, a tag, a commit)')
    ap.add_argument('--set', action='append', default=[], metavar='NAME=VALUE',
                    help='override a model constant for the candidate (repeatable)')
    args = ap.parse_args()

    solar = common.SolarHistory()
    rows  = load_soundings(args.min_cs)
    obs   = np.array([r[5] for r in rows])
    lat   = np.array([r[2] for r in rows])
    lt    = np.array([(r[4].hour + r[4].minute / 60 + r[3] / 15) % 24 for r in rows])
    codes = np.array([r[0] for r in rows])

    models = {'candidate': model_fof2(common.load_model(overrides=args.set), rows, solar)}
    if args.baseline:
        base = common.load_model(args.baseline)
        if not hasattr(base, '_fof2'):
            raise SystemExit(f'{args.baseline} predates _fof2 (2609.003) — pick a newer baseline')
        models['baseline'] = model_fof2(base, rows, solar)

    sfis = [solar.sfi(r[4]) for r in rows]
    print(f'{len(rows)} soundings, {len(set(codes))} stations, {min(r[4] for r in rows):%Y-%m-%d} to '
          f'{max(r[4] for r in rows):%Y-%m-%d}, SFI {min(sfis):.0f}-{max(sfis):.0f}')

    for name, mod in models.items():
        print(f'\n=== {name} ===\nfoF2 by station (MHz)')
        for code in sorted(set(codes), key=lambda c: -lat[codes == c][0]):
            mk = codes == code
            label = f'{code:6s} {rows[int(np.argmax(mk))][1][:24]:24s} {lat[mk][0]:6.1f}'
            print('  ' + summarize(label, obs[mk], mod[mk]))
        for band_label, cond in LAT_BANDS:
            grp = cond(np.abs(lat))
            if grp.any():
                print(f'{band_label}: foF2 by local solar time')
                for lo, hi, bin_label in LT_BINS:
                    mk = grp & (lt >= lo) & (lt < hi)
                    if mk.any():
                        print('  ' + summarize(f'{bin_label:16s}', obs[mk], mod[mk]))

        _, m3000 = common.propagation._hop_geometry(np.array(3000.0))
        mu  = np.array([r[6] is not None for r in rows])
        muf = np.array([r[6] for r in rows if r[6] is not None], float)
        print(summarize('MUF(3000) all   ', muf, mod[mu] * float(m3000)))

    mid = (np.abs(lat) >= 25) & (np.abs(lat) <= 55)
    resid = np.log(obs[mid] / models['candidate'][mid])
    obs_m = np.array([r[6] / r[5] for r in rows if r[6]])
    print(f'\nday-to-day scatter (mid-lat, candidate): sigma(ln foF2) {resid.std():.3f} '
          f'(model uses _MUF_SIGMA {common.propagation._MUF_SIGMA}); '
          f'observed M(3000) median {np.median(obs_m):.2f}')


if __name__ == '__main__':
    main()
