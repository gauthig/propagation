"""Download a validation window: ionosonde history, solar flux, Kp and WSPR reception.

    .\\venv\\Scripts\\python.exe tools\\validate\\fetch_data.py --days 7 --bands 20m,40m

Everything lands in tools/validate/data/ (git-ignored); re-running overwrites it.
"""
import argparse
import datetime as dt
import json
import os

import common

KC2G     = 'https://prop.kc2g.com/api'
WSPR_DB  = 'https://db1.wspr.live/'
NOAA_SFI = 'https://services.swpc.noaa.gov/json/f107_cm_flux.json'
NOAA_KP  = 'https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json'   # last ~7 days only


def save(name, body):
    path = common.data_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(body)
    return path


def fetch_solar():
    save('f107.json', common.http_get(NOAA_SFI, timeout=60))
    save('kp.json', common.http_get(NOAA_KP, timeout=60))
    print('solar: F10.7 + Kp saved')


# ── Ionosondes (GIRO data via KC2G — GIRO's own DIDBGetValues service returned 404 in Sep 2026) ──

def fetch_ionosondes(days, codes, max_age_h):
    stations = json.loads(common.http_get(f'{KC2G}/stations.json', timeout=120))
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    chosen = []
    for r in stations:
        st = r['station']
        if codes:
            if st['code'] in codes:
                chosen.append(st)
        elif r.get('time') and r.get('fof2') and \
                (now - dt.datetime.fromisoformat(r['time'])).total_seconds() < max_age_h * 3600:
            chosen.append(st)
    print(f'ionosondes: {len(chosen)} stations')
    for st in chosen:
        # history.json takes KC2G's numeric station id, not the URSI code
        body = common.http_get(f'{KC2G}/history.json', {'station': st['id'], 'days': days})
        rows = json.loads(body)
        n = len(rows[0].get('history', [])) if rows else 0
        save(os.path.join('ionosonde', f'{st["code"]}.json'), body)
        print(f'   {st["code"]:6s} {st["name"][:30]:30s} {n:5d} soundings')


# ── WSPR (wspr.live public ClickHouse) ───────────────────────────────────────

def fetch_wspr(days, band_name, grid):
    band_code = common.BANDS[band_name][1]
    end   = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    start = end - dt.timedelta(days=days)
    window = f"band = {band_code} AND time >= toDateTime('{start}') AND time < toDateTime('{end}')"
    queries = {
        # Every station decoding anything on the band, per hour — who was listening
        'active': f"""SELECT toStartOfHour(time) AS h, rx_sign,
                             round(avg(rx_lat), 2) AS lat, round(avg(rx_lon), 2) AS lon
                      FROM wspr.rx WHERE {window} GROUP BY h, rx_sign FORMAT TSVWithNames""",
        # Receivers that decoded a transmitter in the home grid, per hour
        'heard': f"""SELECT toStartOfHour(time) AS h, rx_sign, count() AS spots, max(snr) AS best_snr
                     FROM wspr.rx WHERE {window} AND match(tx_loc, '{grid}')
                     GROUP BY h, rx_sign FORMAT TSVWithNames""",
        # Home-grid transmitters on the air, per hour
        'tx': f"""SELECT toStartOfHour(time) AS h, uniqExact(tx_sign) AS n_tx
                  FROM wspr.rx WHERE {window} AND match(tx_loc, '{grid}') GROUP BY h FORMAT TSVWithNames""",
    }
    for kind, sql in queries.items():
        body = common.http_get(WSPR_DB, {'query': ' '.join(sql.split())})
        save(f'wspr_{band_name}_{kind}.tsv', body)
        print(f'wspr {band_name} {kind:6s}: {body.count(b"\n") - 1} rows')
    return {'start': str(start), 'end': str(end)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--days', type=int, default=7, help='window length (Kp feed only covers ~7 days)')
    ap.add_argument('--bands', default='20m,40m',
                    help='comma list of WSPR bands (' + ','.join(common.BANDS) + ')')
    ap.add_argument('--grid', default=common.DEFAULT_GRID,
                    help='regex on WSPR tx_loc for "home" transmitters')
    ap.add_argument('--stations', default='',
                    help='comma list of ionosonde URSI codes (default: all fresh ones)')
    ap.add_argument('--max-age-h', type=float, default=6, help='"fresh" = reported within this many hours')
    ap.add_argument('--skip-iono', action='store_true')
    ap.add_argument('--skip-wspr', action='store_true')
    args = ap.parse_args()

    fetch_solar()
    if not args.skip_iono:
        codes = {c.strip() for c in args.stations.split(',') if c.strip()}
        fetch_ionosondes(args.days, codes, args.max_age_h)
    meta = {'fetched': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'days': args.days,
            'grid': args.grid, 'wspr': {}}
    if not args.skip_wspr:
        for band in (b.strip() for b in args.bands.split(',') if b.strip()):
            if band not in common.BANDS:
                raise SystemExit(f'unknown band {band}')
            meta['wspr'][band] = fetch_wspr(args.days, band, args.grid)
    save('meta.json', json.dumps(meta, indent=2).encode())


if __name__ == '__main__':
    main()
