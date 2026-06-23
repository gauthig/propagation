from flask import Flask, render_template, jsonify, request, make_response
import requests
import threading
import time
import base64
import sys
import datetime
import hashlib
import secrets
import hmac
import os
from decimal import Decimal
from io import BytesIO
from propagation import calculate_muf_map, get_solar_indices

import boto3

app = Flask(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
DEFAULT_LAT = 39.8
DEFAULT_LON = -98.6
REFRESH_INTERVAL   = 900   # seconds — local dev background thread
SOLAR_MAX_AGE_SECS = 7200  # 2 hours — DynamoDB cache TTL

BAND_FREQS = {
    '80m': (3.500, 4.000),
    '60m': (5.330, 5.404),
    '40m': (7.000, 7.300),
    '20m': (14.000, 14.350),
    '17m': (18.068, 18.168),
    '15m': (21.000, 21.450),
    '10m': (28.000, 29.700),
}

# ── Auth configuration ─────────────────────────────────────────────────────────
AUTH_COOKIE       = 'hf_auth'
AUTH_COOKIE_DAYS  = 30
HASH_ITERATIONS   = 260_000
SES_SENDER_EMAIL  = os.environ.get('SES_SENDER_EMAIL', '')
SES_REGION        = os.environ.get('AWS_REGION', 'us-east-1')


def _hash_password(password):
    salt = secrets.token_bytes(32)
    key  = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, HASH_ITERATIONS)
    return salt.hex() + ':' + key.hex()


def _verify_password(password, stored_hash):
    try:
        salt_hex, key_hex = stored_hash.split(':', 1)
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt_hex), HASH_ITERATIONS)
        return hmac.compare_digest(key.hex(), key_hex)
    except Exception:
        return False


def _encode_auth_cookie(callsign, token):
    return base64.b64encode(f'{callsign}:{token}'.encode()).decode()


def _decode_auth_cookie(val):
    try:
        decoded = base64.b64decode(val).decode()
        cs, tok = decoded.split(':', 1)
        return cs.upper(), tok
    except Exception:
        return None, None


def _get_current_user():
    val = request.cookies.get(AUTH_COOKIE, '')
    if not val:
        return None
    callsign, token = _decode_auth_cookie(val)
    if not callsign:
        return None
    try:
        resp = _users_table.get_item(Key={'callsign': callsign})
        user = resp.get('Item')
        if not user:
            return None
        if not hmac.compare_digest(user.get('auth_token', ''), token):
            return None
        exp = user.get('auth_expires', '')
        if exp:
            exp_dt = datetime.datetime.fromisoformat(exp)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
            if exp_dt < datetime.datetime.now(datetime.timezone.utc):
                return None
        if user.get('active') is False:
            return None
        return _from_dynamo(user)
    except Exception as e:
        print(f'[auth] get_current_user error: {e}')
        return None


def _set_auth_cookie(response, callsign, token):
    val = _encode_auth_cookie(callsign, token)
    response.set_cookie(
        AUTH_COOKIE, val,
        max_age=AUTH_COOKIE_DAYS * 86400,
        httponly=True,
        samesite='Lax',
        secure=True,
    )
    return response


def _send_reset_email(email, callsign, token):
    print(f'[auth] reset token for {callsign}: {token}')  # always log for debugging
    if not SES_SENDER_EMAIL:
        print('[auth] SES_SENDER_EMAIL not configured — token logged above only')
        return
    try:
        ses = boto3.client('ses', region_name=SES_REGION)
        body = (
            f'Hello {callsign},\n\n'
            f'Your HF Propagation password reset token is: {token}\n\n'
            f'This token expires in 1 hour. If you did not request this, ignore this email.\n\n'
            f'73 de HF Propagation'
        )
        ses.send_email(
            Source=SES_SENDER_EMAIL,
            Destination={'ToAddresses': [email]},
            Message={
                'Subject': {'Data': 'HF Propagation Password Reset'},
                'Body': {'Text': {'Data': body}},
            },
        )
        print(f'[auth] reset email sent to {email[:3]}***')
    except Exception as e:
        print(f'[auth] SES send_email error: {e}')
        raise


# ── DynamoDB ───────────────────────────────────────────────────────────────────
_dynamo      = boto3.resource('dynamodb')
_users_table = _dynamo.Table('hf_users')
_solar_table = _dynamo.Table('hf_solar')


def _to_dynamo(obj):
    """Recursively convert Python floats to Decimal for DynamoDB storage."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo(v) for v in obj]
    return obj


def _from_dynamo(obj):
    """Recursively convert DynamoDB Decimals back to Python floats."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_dynamo(v) for v in obj]
    return obj


# ── Solar DynamoDB history ─────────────────────────────────────────────────────
SOLAR_MAX_ROWS = 100

def _get_solar_db():
    """GetItem on 'current' — O(1), no Scan needed for the freshness check."""
    try:
        resp = _solar_table.get_item(Key={'record_id': 'current'})
        item = resp.get('Item')
        if not item:
            return None
        age = time.time() - float(item.get('timestamp_epoch', 0))
        if age > SOLAR_MAX_AGE_SECS:
            print(f"[dynamo] solar data is {age/3600:.1f} h old — needs refresh")
            return None
        data = _from_dynamo(item)
        data.pop('record_id', None)
        data['last_update'] = data.pop('timestamp_epoch', time.time())
        print(f"[dynamo] solar cache hit — age {age/60:.0f} min, by={data.get('refreshed_by','?')}")
        return data
    except Exception as e:
        print(f"[dynamo] solar read error: {e}")
        return None


def _prune_solar_history():
    """Scan history rows (excludes 'current') and delete oldest if over SOLAR_MAX_ROWS."""
    try:
        resp = _solar_table.scan(
            FilterExpression='record_id <> :cur',
            ExpressionAttributeValues={':cur': 'current'},
            ProjectionExpression='record_id, timestamp_epoch',
        )
        items = resp.get('Items', [])
        if len(items) <= SOLAR_MAX_ROWS:
            return
        items.sort(key=lambda x: float(x.get('timestamp_epoch', 0)))
        to_delete = items[:len(items) - SOLAR_MAX_ROWS]
        with _solar_table.batch_writer() as batch:
            for item in to_delete:
                batch.delete_item(Key={'record_id': item['record_id']})
        print(f"[dynamo] pruned {len(to_delete)} old solar history rows")
    except Exception as e:
        print(f"[dynamo] solar prune error: {e}")


def _put_solar_db(data, refreshed_by='auto'):
    """Update 'current' fast-lookup row and append a timestamped history row."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        base = _to_dynamo({k: v for k, v in data.items() if k != 'last_update'})
        base['timestamp']       = now.isoformat()
        base['timestamp_epoch'] = Decimal(str(now.timestamp()))
        base['refreshed_by']    = refreshed_by or 'auto'

        # Fast-lookup row — always GetItem('current') on reads
        _solar_table.put_item(Item={**base, 'record_id': 'current'})

        # History row — timestamped, never overwritten
        history_id = now.strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
        _solar_table.put_item(Item={**base, 'record_id': history_id})

        print(f"[dynamo] solar written — current + history {history_id} by {base['refreshed_by']}")
        _prune_solar_history()
    except Exception as e:
        print(f"[dynamo] solar write error: {e}")


def _fetch_and_cache_solar(refreshed_by='auto'):
    """Fetch fresh solar data from external APIs and append to DynamoDB history."""
    data = get_solar_indices()
    _put_solar_db(data, refreshed_by=refreshed_by)
    data['last_update'] = time.time()
    return data


def _update_solar_cache(data):
    """Warm the in-process cache after any solar fetch."""
    with _lock:
        _cache['solar']       = data
        _cache['last_update'] = data.get('last_update', time.time())


# ── User tracking ──────────────────────────────────────────────────────────────

def _upsert_user(callsign, ip, session_id=None):
    """Upsert a row keyed by callsign — the stable cross-browser identity."""
    if not callsign:
        return
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        set_expr = 'last_seen = :ts, ip_address = :ip, first_seen = if_not_exists(first_seen, :ts)'
        values   = {':ts': now, ':ip': ip, ':one': 1}
        if session_id:
            set_expr = f'session_id = :sid, {set_expr}'
            values[':sid'] = session_id
        _users_table.update_item(
            Key={'callsign': callsign},
            UpdateExpression=f'SET {set_expr} ADD access_count :one',
            ExpressionAttributeValues=values,
        )
    except Exception as e:
        print(f"[dynamo] upsert_user error: {e}")


def _track_visit(callsign, ip):
    _upsert_user(callsign, ip)


def _track_callsign(callsign, ip, session_id=None):
    if callsign:
        _upsert_user(callsign, ip, session_id=session_id)


def _track_qth(callsign, lat, lon, method):
    """Update QTH coordinates and entry method for a callsign."""
    if not callsign:
        return
    try:
        _users_table.update_item(
            Key={'callsign': callsign},
            UpdateExpression='SET qth_lat = :lat, qth_lon = :lon, qth_method = :m',
            ExpressionAttributeValues={
                ':lat': Decimal(str(lat)),
                ':lon': Decimal(str(lon)),
                ':m':   method,
            },
        )
    except Exception as e:
        print(f"[dynamo] track_qth error: {e}")


# ── In-process cache (warm Lambda instance / local dev) ───────────────────────
_lock  = threading.Lock()
_cache = {
    'solar': None, 'last_update': None,
    'cache_lat': DEFAULT_LAT, 'cache_lon': DEFAULT_LON,
    '20m': None, '40m': None,
}


def _refresh_loop():
    """Local dev background thread — pre-warms 20m/40m heatmap every 15 min."""
    while True:
        try:
            print("[refresh] fetching solar indices...")
            solar = _fetch_and_cache_solar()
            with _lock:
                lat = _cache['cache_lat']
                lon = _cache['cache_lon']
            print("[refresh] pre-computing 20m and 40m...")
            data_20m = calculate_muf_map(lat, lon, *BAND_FREQS['20m'], solar)
            data_40m = calculate_muf_map(lat, lon, *BAND_FREQS['40m'], solar)
            with _lock:
                _cache['solar']       = solar
                _cache['20m']         = data_20m
                _cache['40m']         = data_40m
                _cache['last_update'] = time.time()
            print(f"[refresh] done — 20m={len(data_20m)} pts, 40m={len(data_40m)} pts")
        except Exception as e:
            print(f"[refresh] ERROR: {e}")
            import traceback; traceback.print_exc()
        time.sleep(REFRESH_INTERVAL)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html',
                           default_lat=DEFAULT_LAT,
                           default_lon=DEFAULT_LON)


# ── Tracking endpoints ─────────────────────────────────────────────────────────

@app.route('/track/visit', methods=['POST'])
def track_visit():
    data     = request.get_json(silent=True) or {}
    callsign = data.get('callsign', '').upper().strip()
    _track_visit(callsign, request.remote_addr or '0.0.0.0')
    return jsonify({'ok': True})


@app.route('/track/callsign', methods=['POST'])
def track_callsign():
    data       = request.get_json(silent=True) or {}
    callsign   = data.get('callsign', '').upper().strip()
    session_id = data.get('session_id', '')
    _track_callsign(callsign, request.remote_addr or '0.0.0.0', session_id=session_id)
    return jsonify({'ok': True})


@app.route('/track/qth', methods=['POST'])
def track_qth():
    data     = request.get_json(silent=True) or {}
    callsign = data.get('callsign', '').upper().strip()
    lat      = data.get('lat')
    lon      = data.get('lon')
    if callsign and lat is not None and lon is not None:
        _track_qth(callsign, float(lat), float(lon), data.get('method', ''))
    return jsonify({'ok': True})


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/auth/me')
def auth_me():
    user = _get_current_user()
    if not user:
        return jsonify({'logged_in': False})
    return jsonify({
        'logged_in': True,
        'callsign':  user['callsign'],
        'admin':     bool(user.get('admin', False)),
    })


@app.route('/auth/login', methods=['POST'])
def auth_login():
    data     = request.get_json(silent=True) or {}
    callsign = data.get('callsign', '').upper().strip()
    password = data.get('password', '')
    if not callsign or not password:
        return jsonify({'error': 'missing_fields'}), 400
    try:
        item = _users_table.get_item(Key={'callsign': callsign}).get('Item')
        if not item:
            return jsonify({'error': 'callsign_not_found'}), 401
        if not _verify_password(password, item.get('password_hash', '')):
            return jsonify({'error': 'incorrect_password'}), 401
        if item.get('active') is False:
            return jsonify({'error': 'account_deactivated'}), 403
        now    = datetime.datetime.now(datetime.timezone.utc)
        token  = secrets.token_urlsafe(32)
        exp    = (now + datetime.timedelta(days=AUTH_COOKIE_DAYS)).isoformat()
        _users_table.update_item(
            Key={'callsign': callsign},
            UpdateExpression='SET auth_token = :t, auth_expires = :e, last_login = :ts ADD login_count :one',
            ExpressionAttributeValues={':t': token, ':e': exp, ':ts': now.isoformat(), ':one': 1},
        )
        resp = make_response(jsonify({
            'ok': True, 'callsign': callsign, 'admin': bool(item.get('admin', False)),
        }))
        return _set_auth_cookie(resp, callsign, token)
    except Exception as e:
        print(f'[auth] login error: {e}')
        return jsonify({'error': 'server_error'}), 500


@app.route('/auth/register', methods=['POST'])
def auth_register():
    data     = request.get_json(silent=True) or {}
    callsign = data.get('callsign', '').upper().strip()
    password = data.get('password', '')
    email    = data.get('email', '').lower().strip()
    if not callsign or not password or not email:
        return jsonify({'error': 'missing_fields'}), 400
    if len(password) < 8:
        return jsonify({'error': 'password_too_short'}), 400
    try:
        item = _users_table.get_item(Key={'callsign': callsign}).get('Item')
        if item and item.get('password_hash'):
            return jsonify({'error': 'callsign_exists'}), 409
        now    = datetime.datetime.now(datetime.timezone.utc)
        token  = secrets.token_urlsafe(32)
        exp    = (now + datetime.timedelta(days=AUTH_COOKIE_DAYS)).isoformat()
        pw_hash = _hash_password(password)
        _users_table.update_item(
            Key={'callsign': callsign},
            UpdateExpression=(
                'SET password_hash = :ph, email = :em, auth_token = :t, auth_expires = :e, '
                'active = :act, first_seen = if_not_exists(first_seen, :ts), last_seen = :ts, '
                'last_login = :ts ADD login_count :one'
            ),
            ExpressionAttributeValues={
                ':ph': pw_hash, ':em': email, ':t': token, ':e': exp,
                ':act': True, ':ts': now.isoformat(), ':one': 1,
            },
        )
        resp = make_response(jsonify({'ok': True, 'callsign': callsign, 'admin': False}))
        return _set_auth_cookie(resp, callsign, token)
    except Exception as e:
        print(f'[auth] register error: {e}')
        return jsonify({'error': 'server_error'}), 500


@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    user = _get_current_user()
    if user:
        try:
            _users_table.update_item(
                Key={'callsign': user['callsign']},
                UpdateExpression='REMOVE auth_token, auth_expires',
            )
        except Exception:
            pass
    resp = make_response(jsonify({'ok': True}))
    resp.delete_cookie(AUTH_COOKIE)
    return resp


@app.route('/auth/reset/request', methods=['POST'])
def auth_reset_request():
    data     = request.get_json(silent=True) or {}
    callsign = data.get('callsign', '').upper().strip()
    email_in = data.get('email', '').lower().strip()
    if not callsign:
        return jsonify({'error': 'missing_fields'}), 400
    try:
        item = _users_table.get_item(Key={'callsign': callsign}).get('Item')
        if not item:
            return jsonify({'error': 'callsign_not_found'}), 404
        stored_email = item.get('email', '').lower()
        if not stored_email:
            return jsonify({'error': 'no_email'}), 404
        if email_in and not hmac.compare_digest(email_in, stored_email):
            return jsonify({'error': 'email_mismatch'}), 400
        reset_token = secrets.token_hex(3).upper()  # 6-char hex, easy to type
        exp = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
        _users_table.update_item(
            Key={'callsign': callsign},
            UpdateExpression='SET reset_token = :t, reset_token_expires = :e',
            ExpressionAttributeValues={':t': reset_token, ':e': exp},
        )
        _send_reset_email(stored_email, callsign, reset_token)
        masked = stored_email[:2] + '***@' + stored_email.split('@')[-1] if '@' in stored_email else stored_email[:3] + '***'
        return jsonify({'ok': True, 'email_masked': masked})
    except Exception as e:
        print(f'[auth] reset_request error: {e}')
        return jsonify({'error': 'server_error'}), 500


@app.route('/auth/reset/confirm', methods=['POST'])
def auth_reset_confirm():
    data     = request.get_json(silent=True) or {}
    callsign = data.get('callsign', '').upper().strip()
    token    = data.get('token', '').upper().strip()
    new_pw   = data.get('new_password', '')
    if not all([callsign, token, new_pw]):
        return jsonify({'error': 'missing_fields'}), 400
    if len(new_pw) < 8:
        return jsonify({'error': 'password_too_short'}), 400
    try:
        item = _users_table.get_item(Key={'callsign': callsign}).get('Item')
        if not item:
            return jsonify({'error': 'callsign_not_found'}), 404
        stored = item.get('reset_token', '')
        if not stored or not hmac.compare_digest(stored, token):
            return jsonify({'error': 'invalid_token'}), 400
        exp = item.get('reset_token_expires', '')
        if exp:
            exp_dt = datetime.datetime.fromisoformat(exp)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
            if exp_dt < datetime.datetime.now(datetime.timezone.utc):
                return jsonify({'error': 'token_expired'}), 400
        pw_hash  = _hash_password(new_pw)
        new_tok  = secrets.token_urlsafe(32)
        new_exp  = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=AUTH_COOKIE_DAYS)).isoformat()
        _users_table.update_item(
            Key={'callsign': callsign},
            UpdateExpression='SET password_hash = :ph, auth_token = :at, auth_expires = :ae REMOVE reset_token, reset_token_expires',
            ExpressionAttributeValues={':ph': pw_hash, ':at': new_tok, ':ae': new_exp},
        )
        resp = make_response(jsonify({'ok': True, 'callsign': callsign, 'admin': bool(item.get('admin', False))}))
        return _set_auth_cookie(resp, callsign, new_tok)
    except Exception as e:
        print(f'[auth] reset_confirm error: {e}')
        return jsonify({'error': 'server_error'}), 500


# ── Admin ──────────────────────────────────────────────────────────────────────

@app.route('/admin/users')
def admin_list_users():
    user = _get_current_user()
    if not user or not user.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        resp = _users_table.scan(
            ProjectionExpression='callsign, first_seen, last_login, login_count, active, #adm, email',
            ExpressionAttributeNames={'#adm': 'admin'},
        )
        users = sorted(
            [_from_dynamo(u) for u in resp.get('Items', [])],
            key=lambda u: u.get('last_login') or u.get('first_seen') or '',
            reverse=True,
        )
        return jsonify(users)
    except Exception as e:
        print(f'[admin] list_users error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/admin/users/deactivate', methods=['POST'])
def admin_deactivate_user():
    user = _get_current_user()
    if not user or not user.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    data   = request.get_json(silent=True) or {}
    target = data.get('callsign', '').upper().strip()
    active = data.get('active', False)
    if not target:
        return jsonify({'error': 'Callsign required'}), 400
    try:
        if active:
            _users_table.update_item(
                Key={'callsign': target},
                UpdateExpression='SET active = :act',
                ExpressionAttributeValues={':act': True},
            )
        else:
            _users_table.update_item(
                Key={'callsign': target},
                UpdateExpression='SET active = :act REMOVE auth_token, auth_expires',
                ExpressionAttributeValues={':act': False},
            )
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/admin/users/reset-password', methods=['POST'])
def admin_reset_user_password():
    user = _get_current_user()
    if not user or not user.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    data   = request.get_json(silent=True) or {}
    target = data.get('callsign', '').upper().strip()
    new_pw = data.get('password', '')
    if not target or not new_pw:
        return jsonify({'error': 'Callsign and password required'}), 400
    if len(new_pw) < 8:
        return jsonify({'error': 'password_too_short'}), 400
    try:
        pw_hash = _hash_password(new_pw)
        _users_table.update_item(
            Key={'callsign': target},
            UpdateExpression='SET password_hash = :ph, active = :act REMOVE auth_token, auth_expires',
            ExpressionAttributeValues={':ph': pw_hash, ':act': True},
        )
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Solar ──────────────────────────────────────────────────────────────────────

@app.route('/solar')
def solar_data():
    try:
        data = _get_solar_db() or _fetch_and_cache_solar()
        _update_solar_cache(data)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e), 'stale': True}), 500


@app.route('/solar/refresh', methods=['POST'])
def solar_refresh():
    """Force a fresh solar fetch regardless of cache age. WB0Z-only button calls this."""
    try:
        body         = request.get_json(silent=True) or {}
        refreshed_by = body.get('callsign', 'manual').upper().strip() or 'manual'
        data = _fetch_and_cache_solar(refreshed_by=refreshed_by)
        _update_solar_cache(data)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e), 'stale': True}), 500


# ── Heatmap ────────────────────────────────────────────────────────────────────

@app.route('/heatmap/<band>')
def heatmap(band):
    if band not in BAND_FREQS:
        return jsonify({'error': f'Invalid band. Valid: {list(BAND_FREQS.keys())}'}), 400

    try:
        req_lat = float(request.args.get('lat', DEFAULT_LAT))
        req_lon = float(request.args.get('lon', DEFAULT_LON))
    except (TypeError, ValueError):
        req_lat, req_lon = DEFAULT_LAT, DEFAULT_LON

    antenna_type = request.args.get('antenna', 'vertical')
    if antenna_type not in ('vertical', 'dipole', 'hex_beam'):
        antenna_type = 'vertical'
    try:
        height_ft = float(request.args.get('height_ft', 30))
    except (TypeError, ValueError):
        height_ft = 30.0
    height_m = height_ft * 0.3048

    beam_azimuth = None
    if antenna_type == 'hex_beam' and 'azimuth' in request.args:
        try:
            beam_azimuth = float(request.args.get('azimuth', 0)) % 360
        except (TypeError, ValueError):
            beam_azimuth = 0.0

    try:
        dipole_orient = float(request.args.get('dipole_orient', 0)) % 180
    except (TypeError, ValueError):
        dipole_orient = 0.0

    use_cache = (antenna_type == 'vertical')

    with _lock:
        solar     = _cache['solar']
        cache_lat = _cache['cache_lat']
        cache_lon = _cache['cache_lon']
        same_loc  = (abs(req_lat - cache_lat) < 0.5 and abs(req_lon - cache_lon) < 0.5)
        data      = _cache.get(band) if (same_loc and use_cache) else None

    if solar is None or data is None:
        # Pull solar from DynamoDB if not in process cache
        if solar is None:
            solar = _get_solar_db() or _fetch_and_cache_solar()
        freq_min, freq_max = BAND_FREQS[band]
        data = calculate_muf_map(req_lat, req_lon, freq_min, freq_max, solar,
                                 antenna_type=antenna_type, height_m=height_m,
                                 beam_azimuth=beam_azimuth, dipole_orient=dipole_orient)
        if same_loc and use_cache and band in ('20m', '40m'):
            _update_solar_cache(solar)
            with _lock:
                _cache[band] = data

    return jsonify(data)


# ── ZIP geocoding ──────────────────────────────────────────────────────────────

@app.route('/zip/<zipcode>')
def zip_lookup(zipcode):
    if not zipcode.isdigit() or len(zipcode) > 5:
        return jsonify({'error': 'Invalid ZIP code format'}), 400
    try:
        r = requests.get(
            f'https://api.zippopotam.us/us/{zipcode}',
            timeout=8,
            headers={'User-Agent': 'hf-propagation/1.0'},
        )
        if r.status_code == 404:
            return jsonify({'error': f'ZIP code {zipcode} not found'}), 404
        if not r.ok:
            return jsonify({'error': 'ZIP lookup service unavailable'}), 502
        d     = r.json()
        place = d['places'][0]
        return jsonify({
            'zipcode': zipcode,
            'city':    place['place name'],
            'state':   place['state abbreviation'],
            'lat':     float(place['latitude']),
            'lon':     float(place['longitude']),
        })
    except requests.RequestException as e:
        return jsonify({'error': f'Network error: {e}'}), 502
    except (KeyError, IndexError, ValueError):
        return jsonify({'error': 'Unexpected response from ZIP service'}), 500


# ── Lambda WSGI adapter ────────────────────────────────────────────────────────

def handler(event, context):
    """Minimal WSGI adapter for Lambda Function URLs (payload format v2.0)."""
    http    = event['requestContext']['http']
    path    = event.get('rawPath', '/')
    qs      = event.get('rawQueryString', '') or ''
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}

    body = event.get('body') or ''
    body_bytes = base64.b64decode(body) if event.get('isBase64Encoded') else body.encode()

    environ = {
        'REQUEST_METHOD':   http['method'],
        'PATH_INFO':        path,
        'QUERY_STRING':     qs,
        'CONTENT_TYPE':     headers.get('content-type', ''),
        'CONTENT_LENGTH':   str(len(body_bytes)),
        'REMOTE_ADDR':      http.get('sourceIp', '0.0.0.0'),
        'SERVER_NAME':      'lambda',
        'SERVER_PORT':      '443',
        'SERVER_PROTOCOL':  'HTTP/1.1',
        'wsgi.version':     (1, 0),
        'wsgi.url_scheme':  'https',
        'wsgi.input':       BytesIO(body_bytes),
        'wsgi.errors':      sys.stderr,
        'wsgi.multithread':  False,
        'wsgi.multiprocess': False,
        'wsgi.run_once':     False,
    }
    for k, v in headers.items():
        key = k.upper().replace('-', '_')
        if key not in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            environ[f'HTTP_{key}'] = v

    status_holder, resp_headers = {}, {}

    def start_response(status, response_headers, exc_info=None):
        status_holder['code'] = int(status.split(' ', 1)[0])
        resp_headers.update(dict(response_headers))

    body_out = b''.join(app(environ, start_response))
    ct = resp_headers.get('Content-Type', '')
    is_binary = not (ct.startswith('text/') or 'json' in ct)

    return {
        'statusCode':      status_holder.get('code', 200),
        'headers':         resp_headers,
        'body':            base64.b64encode(body_out).decode() if is_binary else body_out.decode(),
        'isBase64Encoded': is_binary,
    }


if __name__ == '__main__':
    t = threading.Thread(target=_refresh_loop, daemon=True)
    t.start()
    app.run(debug=True, use_reloader=False)
