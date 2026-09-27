"""Score the heatmap against WSPR reception of home-grid transmitters.

Unit of evaluation: (hour, receiver that decoded anything on the band that hour, ≥ --min-km away).
Label: did it decode a home-grid transmitter that hour? Score: the model's strength at its cell.

    .\\venv\\Scripts\\python.exe tools\\validate\\wspr.py --band 20m
    .\\venv\\Scripts\\python.exe tools\\validate\\wspr.py --band 40m --baseline HEAD~1 --split "2026-09-24 12"
    .\\venv\\Scripts\\python.exe tools\\validate\\wspr.py --band 20m --set _AUR_DB=25 --set _AUR_WIDTH=5.0
"""
import argparse
import csv
import datetime as dt

import numpy as np

import common

STRENGTH_BINS = [(-1, 0.03, 'dark <=0.03'), (0.03, 0.12, '0.03-0.12'), (0.12, 0.35, '0.12-0.35'),
                 (0.35, 0.6, '0.35-0.60'), (0.6, 1.01, '0.60-1.00')]


def read_tsv(name):
    with open(common.require(common.data_path(name)), encoding='utf-8') as f:
        return list(csv.DictReader(f, delimiter='\t'))


def load_samples(band, qth, min_km):
    heard = {(r['h'], r['rx_sign']) for r in read_tsv(f'wspr_{band}_heard.tsv')}
    tx_hours = {r['h'] for r in read_tsv(f'wspr_{band}_tx.tsv') if int(r['n_tx']) > 0}
    samples = []
    for r in read_tsv(f'wspr_{band}_active.tsv'):
        if r['h'] not in tx_hours:                 # nobody at home transmitting → no information
            continue
        lat, lon = float(r['lat']), float(r['lon'])
        if common.gc_km(qth[0], qth[1], lat, lon) >= min_km:
            samples.append((r['h'], lat, lon, (r['h'], r['rx_sign']) in heard))
    if not samples:
        raise SystemExit(f'no usable WSPR samples for {band} — run fetch_data.py --bands {band}')
    return samples


def predict(mod, samples, band, qth, solar):
    freqs = common.BANDS[band][0]
    maps = {}
    for h in sorted({s[0] for s in samples}):
        t = dt.datetime.fromisoformat(h).replace(tzinfo=dt.timezone.utc) + dt.timedelta(minutes=30)
        maps[h] = {(a, b): v for a, b, v in common.run_map(mod, qth, freqs, solar.solar(t), t)}
    return np.array([maps[h].get(common.grid_cell(lat, lon), 0.0) for h, lat, lon, _y in samples])


def fmt_pct(x):
    return '   n/a' if np.isnan(x) else f'{x:6.1%}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--band', default='20m', choices=list(common.BANDS))
    ap.add_argument('--qth', default=f'{common.DEFAULT_QTH[0]},{common.DEFAULT_QTH[1]}',
                    help='lat,lon to model from — the centre of the --grid used when fetching')
    ap.add_argument('--min-km', type=float, default=300, help='closer receivers are ground wave, not skywave')
    ap.add_argument('--split', help='"YYYY-MM-DD HH:MM" — also report AUC before (train) / after (test)')
    ap.add_argument('--baseline', help='git ref to compare against (e.g. HEAD~1, a tag, a commit)')
    ap.add_argument('--set', action='append', default=[], metavar='NAME=VALUE',
                    help='override a model constant for the candidate (repeatable)')
    args = ap.parse_args()

    qth     = tuple(float(v) for v in args.qth.split(','))
    solar   = common.SolarHistory()
    samples = load_samples(args.band, qth, args.min_km)
    y   = np.array([s[3] for s in samples])
    reg = np.array([common.region(s[1], s[2]) for s in samples])
    lt  = np.array([(dt.datetime.fromisoformat(s[0]).hour + 0.5 + qth[1] / 15) % 24 for s in samples])
    split = dt.datetime.fromisoformat(args.split).strftime('%Y-%m-%d %H:%M:%S') if args.split else None
    train = np.array([s[0] < split for s in samples]) if split else None

    preds = {}
    if args.baseline:
        preds['baseline'] = predict(common.load_model(args.baseline), samples, args.band, qth, solar)
    preds['candidate'] = predict(common.load_model(overrides=args.set), samples, args.band, qth, solar)
    names = list(preds)

    hours = sorted({s[0] for s in samples})
    print(f'{args.band}: {len(samples)} receiver-hours >= {args.min_km:.0f} km over {len(hours)} hours '
          f'({hours[0]} to {hours[-1]} UTC); {y.mean():.1%} heard the home grid')
    def row(label, fn, fmt):
        print(f'{label:38s}' + ''.join(format(fn(preds[n]), fmt).rjust(14) for n in names))

    print('\n' + ' ' * 38 + ''.join(f'{n:>14s}' for n in names))
    row('AUC (ranks heard above not-heard)', lambda p: common.auc(p, y), '.3f')
    if train is not None:
        row('AUC train (before split)', lambda p: common.auc(p[train], y[train]), '.3f')
        row('AUC test  (after split)', lambda p: common.auc(p[~train], y[~train]), '.3f')
    row('heard paths shown dark (<=0.03)', lambda p: np.mean(p[y] <= 0.03), '.1%')
    row('heard paths not drawn (<0.12)', lambda p: np.mean(p[y] < 0.12), '.1%')

    print('\nReliability: share of receivers that heard the home grid, by predicted strength')
    for n in names:
        cells = []
        for lo, hi, label in STRENGTH_BINS:
            mk = (preds[n] > lo) & (preds[n] <= hi)
            cells.append(f'{label} {fmt_pct(y[mk].mean() if mk.any() else np.nan)} (n={mk.sum()})')
        print(f'  {n:10s} ' + ' | '.join(cells))

    print('\nBy region' + ' ' * 17 + 'heard       n   ' + '   '.join(f'AUC/mean {n}' for n in names))
    for rg in common.REGIONS:
        mk = reg == rg
        if mk.sum() >= 50:
            cells = [f'{common.auc(preds[n][mk], y[mk]):.2f}/{preds[n][mk].mean():.2f}'.ljust(len(n) + 9)
                     for n in names]
            print(f'  {rg:22s} {y[mk].mean():6.1%} {mk.sum():7d}   ' + '   '.join(cells))

    print(f'\nBy local solar time at the QTH (lon {qth[1]:.1f})   heard   mean predicted '
          + ' / '.join(names))
    for lo in range(0, 24, 3):
        mk = (lt >= lo) & (lt < lo + 3)
        if mk.any():
            print(f'  {lo:02d}-{lo + 3:02d}' + ' ' * 38 + f'{y[mk].mean():6.1%}   ' +
                  ' / '.join(f'{preds[n][mk].mean():.2f}' for n in names))


if __name__ == '__main__':
    main()
