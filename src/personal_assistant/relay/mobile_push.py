"""Native Companion delivery: durable per-phone events and FCM data hints.

Provider acceptance and handset acknowledgement are separate records. Hints contain
no task text, credential or signed URL; paired HTTPS fetches recover the full event.
"""
import asyncio
import base64
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field


class MobileEventStore:
    def __init__(self, devices):
        self.devices = devices
        self.clock = devices.clock
        with devices.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS native_push (
                phone TEXT PRIMARY KEY,provider TEXT NOT NULL,token TEXT NOT NULL,updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS native_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,phone TEXT NOT NULL,
                fingerprint TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,
                accepted REAL,received REAL,attempts INTEGER NOT NULL DEFAULT 0,due REAL NOT NULL,
                UNIQUE(phone,fingerprint));
                CREATE INDEX IF NOT EXISTS native_phone_events ON native_events(phone,sequence);
                CREATE TABLE IF NOT EXISTS native_snoozes (
                id TEXT PRIMARY KEY,phone TEXT NOT NULL,event_id TEXT NOT NULL,seconds INTEGER NOT NULL,
                due REAL NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'waiting');
                CREATE TABLE IF NOT EXISTS native_push_health (
                phone TEXT PRIMARY KEY,last_ok REAL,last_error TEXT,last_error_at REAL);''')

    def register(self, phone, provider, token):
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM native_push WHERE token=? AND phone!=?', (token, phone))
            db.execute('DELETE FROM native_push_health WHERE phone=?', (phone,))
            db.execute('INSERT INTO native_push VALUES(?,?,?,?) ON CONFLICT(phone) DO UPDATE SET provider=excluded.provider,token=excluded.token,updated=excluded.updated',
                       (phone, provider, token, self.clock()))
            db.execute('UPDATE native_events SET due=?,accepted=NULL WHERE phone=? AND received IS NULL AND expires>?',
                       (self.clock(), phone, self.clock()))
        return {'registered': True, 'provider': provider}

    def unregister(self, phone):
        with self.devices.db() as db:
            db.execute('DELETE FROM native_push WHERE phone=?', (phone,))

    def active(self, phone):
        with self.devices.db() as db:
            return db.execute('SELECT id FROM phones WHERE id=? AND revoked=0', (phone,)).fetchone() is not None

    def enqueue(self, payload, ttl=86400, phone=None, repeat=''):
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT id FROM phones WHERE revoked=0' + (' AND id=?' if phone else ''),
                              (phone,) if phone else ()).fetchall()
            for row in rows:
                fingerprint = self.fingerprint(db, row['id'], payload.get('tag', ''), encoded, repeat)
                if not fingerprint:
                    continue
                identifier = hashlib.sha256((row['id'] + ':' + fingerprint).encode()).hexdigest()
                db.execute('''INSERT OR IGNORE INTO native_events(id,phone,fingerprint,payload,created,expires,due)
                           VALUES(?,?,?,?,?,?,?)''', (identifier, row['id'], fingerprint, encoded,
                           self.clock(), self.clock() + min(86400, max(1, ttl)), self.clock()))
        return len(rows)

    @staticmethod
    def fingerprint(db, phone, tag, encoded, repeat):
        """Re-sending a tag's newest content is a producer retry. Content that returns after another
        state, or an explicit repeat key, is a new event; the key keeps repeated retries idempotent."""
        content = hashlib.sha256(encoded.encode()).hexdigest()
        if repeat:
            return hashlib.sha256((content + ':' + repeat).encode()).hexdigest()
        newest = db.execute("SELECT payload FROM native_events WHERE phone=? AND COALESCE(json_extract(payload,'$.tag'),'')=? ORDER BY sequence DESC LIMIT 1",
                            (phone, tag)).fetchone()
        if newest and newest['payload'] == encoded:
            return None
        if db.execute('SELECT 1 FROM native_events WHERE phone=? AND fingerprint=?', (phone, content)).fetchone():
            last = db.execute('SELECT MAX(sequence) FROM native_events WHERE phone=?', (phone,)).fetchone()[0]
            return hashlib.sha256((content + ':after:' + str(last)).encode()).hexdigest()
        return content

    def events(self, phone, cursor=0, limit=100):
        self.materialize_snoozes()
        with self.devices.db() as db:
            rows = db.execute('SELECT sequence,id,payload,created,expires FROM native_events WHERE phone=? AND sequence>? ORDER BY sequence LIMIT ?',
                              (phone, cursor, limit)).fetchall()
        return {'items': [{**dict(row), 'payload': json.loads(row['payload'])} for row in rows],
                'next_cursor': rows[-1]['sequence'] if rows else cursor, 'more': len(rows) == limit}

    def snooze(self, phone, identifier, event_id, seconds):
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM native_snoozes WHERE id=?', (identifier,)).fetchone()
            if old:
                if old['phone'] != phone or old['event_id'] != event_id or old['seconds'] != seconds:
                    raise ValueError('Snooze request ID already has different contents.')
                return {'id': identifier, 'due': old['due'], 'saved': True}
            event = db.execute('SELECT payload,created FROM native_events WHERE id=? AND phone=?', (event_id, phone)).fetchone()
            if not event or self.clock() - event['created'] > 86400:
                raise ValueError('Reminder is no longer available to snooze.')
            payload = json.loads(event['payload'])
            if payload.get('type') != 'reminder':
                raise ValueError('Only calendar reminders can be snoozed.')
            payload['snooze_id'] = identifier
            due = self.clock() + seconds
            db.execute('INSERT INTO native_snoozes(id,phone,event_id,seconds,due,payload) VALUES(?,?,?,?,?,?)',
                       (identifier, phone, event_id, seconds, due, json.dumps(payload, sort_keys=True)))
        return {'id': identifier, 'due': due, 'saved': True}

    def materialize_snoozes(self):
        # Allocate delivery sequence only when due: a later immediate event must
        # not move the phone's cursor past an as-yet undelivered snoozed reminder.
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute("SELECT * FROM native_snoozes WHERE state='waiting' AND due<=?", (self.clock(),)).fetchall():
                active = db.execute('SELECT id FROM phones WHERE id=? AND revoked=0', (row['phone'],)).fetchone()
                if active:
                    fingerprint = hashlib.sha256(row['payload'].encode()).hexdigest()
                    identifier = hashlib.sha256((row['phone'] + ':' + fingerprint).encode()).hexdigest()
                    db.execute('''INSERT OR IGNORE INTO native_events(id,phone,fingerprint,payload,created,expires,due)
                               VALUES(?,?,?,?,?,?,?)''', (identifier,row['phone'],fingerprint,row['payload'],
                               self.clock(),self.clock()+3600,self.clock()))
                db.execute("UPDATE native_snoozes SET state='delivered' WHERE id=?", (row['id'],))

    def receipt(self, phone, cursor):
        with self.devices.db() as db:
            maximum = db.execute('SELECT MAX(sequence) FROM native_events WHERE phone=?', (phone,)).fetchone()[0] or 0
            if cursor > maximum:
                raise ValueError('Unknown notification cursor.')
            db.execute('UPDATE native_events SET received=? WHERE phone=? AND sequence<=? AND received IS NULL',
                       (self.clock(), phone, cursor))
        return {'received': cursor}

    def pending(self):
        with self.devices.db() as db:
            return [dict(row) for row in db.execute('''SELECT event.*,push.provider,push.token FROM native_events event
                JOIN native_push push ON push.phone=event.phone JOIN phones phone ON phone.id=event.phone
                WHERE phone.revoked=0 AND event.received IS NULL AND event.accepted IS NULL
                    AND event.expires>? AND event.due<=? ORDER BY event.sequence LIMIT 100''',
                    (self.clock(), self.clock()))]

    def outcome(self, identifier, accepted, error=None, token=None):
        with self.devices.db() as db:
            row = db.execute('SELECT attempts,phone FROM native_events WHERE id=?', (identifier,)).fetchone()
            if not row:
                return
            attempts = row['attempts'] + 1
            db.execute('UPDATE native_events SET accepted=?,attempts=?,due=? WHERE id=?',
                       (self.clock() if accepted else None, attempts,
                        self.clock() + min(3600, 5 * 2 ** min(attempts, 10)), identifier))
            if accepted:
                # An accepted hint ends the error: the status reports the current condition, not history.
                db.execute('INSERT INTO native_push_health(phone,last_ok) VALUES(?,?) ON CONFLICT(phone) DO UPDATE SET last_ok=excluded.last_ok,last_error=NULL,last_error_at=NULL',
                           (row['phone'], self.clock()))
                return
            code = reason(error)
            db.execute('''INSERT INTO native_push_health(phone,last_error,last_error_at) VALUES(?,?,?)
                       ON CONFLICT(phone) DO UPDATE SET last_error=excluded.last_error,last_error_at=excluded.last_error_at''',
                       (row['phone'], code, self.clock()))
            if code == 'UNREGISTERED' and token:
                # Compare-and-delete: a token the phone has since rotated must survive.
                db.execute('DELETE FROM native_push WHERE phone=? AND token=?', (row['phone'], token))

    def overview(self):
        """Owner view of native delivery: opaque ids, times and counts, never content or tokens."""
        now = self.clock()
        with self.devices.db() as db:
            phones = [dict(row) for row in db.execute('''SELECT phone.id,phone.created,phone.seen,push.updated registered_at,
                health.last_ok,health.last_error,health.last_error_at FROM phones phone
                LEFT JOIN native_push push ON push.phone=phone.id LEFT JOIN native_push_health health ON health.phone=phone.id
                WHERE phone.revoked=0 ORDER BY phone.created''')]
            for phone in phones:
                events = db.execute('''SELECT MAX(accepted) accepted,MAX(received) received,
                    COALESCE(SUM(received IS NULL AND expires>?),0) unreceived,
                    MIN(CASE WHEN received IS NULL AND expires>? THEN created END) oldest
                    FROM native_events WHERE phone=?''', (now, now, phone['id'])).fetchone()
                phone.update(registered=phone['registered_at'] is not None, last_accepted=events['accepted'],
                             last_receipt=events['received'], unreceived=events['unreceived'],
                             oldest_unreceived_age=None if events['oldest'] is None else max(0, now - events['oldest']),
                             last_error=phone['last_error'] and {'code': phone['last_error'], 'at': phone['last_error_at']})
                phone.pop('last_error_at')
        errors = [phone['last_error'] for phone in phones if phone['last_error']]
        ages = [phone['oldest_unreceived_age'] for phone in phones if phone['oldest_unreceived_age'] is not None]
        return {'time': now, 'phones': phones,
                'last_accepted': max((phone['last_accepted'] for phone in phones if phone['last_accepted']), default=None),
                'last_receipt': max((phone['last_receipt'] for phone in phones if phone['last_receipt']), default=None),
                'unreceived': sum(phone['unreceived'] for phone in phones), 'oldest_unreceived_age': max(ages, default=None),
                'last_error': max(errors, key=lambda error: error['at'], default=None)}

    def status(self, phone):
        with self.devices.db() as db:
            registered = db.execute('SELECT provider,updated FROM native_push WHERE phone=?', (phone,)).fetchone()
            pending = db.execute('SELECT COUNT(*) FROM native_events WHERE phone=? AND received IS NULL AND expires>?',
                                 (phone, self.clock())).fetchone()[0]
        return {'registered': registered is not None, 'provider': registered['provider'] if registered else None,
                'pending': pending, 'handset_delivery_verified': False}


class CompanionSender:
    """Adapt current task/reminder/release producers into native, app-open events."""
    def __init__(self, store):
        self.store = store
        self.fingerprint_namespace = 'native-companion-v1'

    def renotify(self, payload, revision):
        self(payload, 'revision-' + str(revision))

    def __call__(self, payload, repeat=''):
        data = payload.get('data', {})
        tag = data.get('tag', '')
        body = {'title': payload.get('title', 'Assistant'), 'message': payload.get('message', ''),
                'tag': tag, 'created': self.store.clock(), 'visibility': data.get('visibility', 'private')}
        if payload.get('message') == 'command_broadcast_intent':
            body = {'type': 'release', 'tag': 'companion-release',
                    'version_code': data.get('version_code'), 'sha256': data.get('sha256')}
        elif tag.startswith('assistant-calendar-'):
            body['type'] = 'reminder'
            body['reminder_id'] = tag.removeprefix('assistant-calendar-')
        elif tag.startswith('assistant-alarm-') or payload.get('message') == 'command_activity':
            body['type'] = 'alarm'
            body['action_id'] = data.get('action_id', tag.removeprefix('assistant-alarm-'))
            if not tag:
                body.update(tag='assistant-alarm-'+body['action_id'],title='Phone alarm request',message='Tap to set the requested alarm.')
        else:
            body['type'] = 'task'
            parsed = urllib.parse.urlsplit(data.get('clickAction', ''))
            match = re.fullmatch(r'/tasks/(agent|command)/([A-Za-z0-9_-]{8,64})', parsed.path)
            if not match:
                raise ValueError('Native task event requires a task conversation target.')
            from .notifications import TITLES
            state = next((state for state, title in TITLES.items() if body['title'].startswith(title)),
                         'running' if data.get('progress_indeterminate') else 'queued')
            body.update(task_kind=match[1], task_id=match[2], active=bool(data.get('persistent')), state=state)
        # Stable producer retries must deduplicate even though their send time changes.
        body.pop('created', None)
        # Reporting success with no recipient would lose the update for a phone paired later.
        if not self.store.enqueue(body, int(data.get('ttl', 86400)), phone=data.get('phone_id'), repeat=repeat):
            raise OSError('No active paired Companion.')


FCM_CODES = {'UNREGISTERED', 'INVALID_ARGUMENT', 'SENDER_ID_MISMATCH', 'QUOTA_EXCEEDED', 'UNAVAILABLE', 'INTERNAL',
             'THIRD_PARTY_AUTH_ERROR', 'UNAUTHENTICATED', 'PERMISSION_DENIED', 'NOT_FOUND'}
OAUTH_CODES = {'INVALID_GRANT', 'INVALID_CLIENT', 'INVALID_REQUEST', 'UNAUTHORIZED_CLIENT', 'INVALID_SCOPE'}
HTTP_CODES = {400: 'INVALID_ARGUMENT', 401: 'UNAUTHENTICATED', 403: 'PERMISSION_DENIED', 404: 'NOT_FOUND', 429: 'QUOTA_EXCEEDED'}


class FcmError(OSError):
    """Provider failure reduced to a whitelisted code. Response bodies can echo registration tokens."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def reason(error):
    return error.code if isinstance(error, FcmError) else type(error).__name__


def fcm_code(error, oauth=False):
    """Code of a failed Google call. OAuth token-endpoint failures carry an OAUTH_ prefix so the owner can
    tell a bad service account from an FCM rejection; unreadable or oddly shaped bodies fall back to the status."""
    try:
        body = json.loads(error.read(4096))
    except Exception:
        body = None
    found = body.get('error') if isinstance(body, dict) else None
    named = []
    if isinstance(found, dict):
        details = found.get('details')
        named = [item.get('errorCode') for item in details if isinstance(item, dict)] if isinstance(details, list) else []
        named.append(found.get('status'))
    elif isinstance(found, str):
        named = [found.upper()]
    code = next((name for name in named if isinstance(name, str) and name in (OAUTH_CODES if oauth else FCM_CODES)), None)
    status = error.code if isinstance(error.code, int) else 0
    code = code or HTTP_CODES.get(status) or ('UNAVAILABLE' if status >= 500 else 'HTTP_' + str(status))
    return ('OAUTH_' if oauth else '') + code


class FcmPush:
    def __init__(self, config, requester=None, signer=None, clock=time.time):
        self.account = json.loads(Path(config['service_account_file']).read_text(encoding='utf-8-sig'))
        self.project = config.get('project_id', self.account.get('project_id', ''))
        if not re.fullmatch(r'[a-z][a-z0-9-]{4,62}', self.project):
            raise ValueError('Invalid Firebase project ID.')
        if self.account.get('type') != 'service_account' or not self.account.get('client_email') or not self.account.get('private_key'):
            raise ValueError('A protected Firebase service account is required.')
        self.requester = requester or self.request
        self.signer = signer or self.sign
        self.clock = clock
        self.token = None
        self.expires = 0

    @staticmethod
    def request(url, payload, headers):
        from .notifications import NoRedirect
        request = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
            return json.load(response)

    def sign(self, body):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        key = serialization.load_pem_private_key(self.account['private_key'].encode(), password=None)
        return key.sign(body, padding.PKCS1v15(), hashes.SHA256())

    def access(self):
        if self.token and self.clock() < self.expires:
            return self.token
        def encoded(value):
            return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')
        now = int(self.clock())
        body = encoded({'alg': 'RS256', 'typ': 'JWT'}) + '.' + encoded({
            'iss': self.account['client_email'], 'scope': 'https://www.googleapis.com/auth/firebase.messaging',
            'aud': 'https://oauth2.googleapis.com/token', 'iat': now, 'exp': now + 3600})
        assertion = body + '.' + base64.urlsafe_b64encode(self.signer(body.encode())).decode().rstrip('=')
        response = self.requester('https://oauth2.googleapis.com/token', urllib.parse.urlencode({
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': assertion}).encode(),
            {'Content-Type': 'application/x-www-form-urlencoded'})
        self.token = response['access_token']
        self.expires = self.clock() + response.get('expires_in', 3600) - 60
        return self.token

    def bearer(self):
        try:
            return self.access()
        except urllib.error.HTTPError as error:
            raise FcmError(fcm_code(error, True)) from None
        except OSError:
            raise FcmError('OAUTH_UNREACHABLE') from None
        except Exception:
            raise FcmError('OAUTH_CREDENTIAL') from None

    def send(self, payload):
        bearer = self.bearer()
        try:
            return self.requester('https://fcm.googleapis.com/v1/projects/' + self.project + '/messages:send',
                                  json.dumps(payload).encode(), {'Authorization': 'Bearer ' + bearer,
                                  'Content-Type': 'application/json'})
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.token = None
                self.expires = 0
            raise FcmError(fcm_code(error)) from None
        except OSError:
            raise FcmError('UNREACHABLE') from None
        except ValueError:
            raise FcmError('BAD_RESPONSE') from None

    def __call__(self, row):
        result = self.send({'message': {'token': row['token'], 'data': {'event_id': row['id'], 'type': 'assistant_event'},
                            'android': {'priority': 'HIGH', 'ttl': str(max(1, int(row['expires'] - self.clock()))) + 's',
                                        'collapse_key': 'assistant_events'}}})
        if not isinstance(result, dict) or not isinstance(result.get('name'), str) or not result['name']:
            raise FcmError('NO_ACK')
        return result

    def dry_run(self):
        """FCM's validate_only flag checks the credential, project and permission without delivering anything."""
        return self.send({'validate_only': True, 'message': {'topic': 'preflight', 'data': {'type': 'preflight'}}})


class MobilePushPump:
    def __init__(self, store, provider=None, interval=2):
        self.store, self.provider, self.interval = store, provider, interval
        self.stop = threading.Event()
        self.thread = None

    def tick(self):
        self.store.materialize_snoozes()
        if not self.provider:
            return
        for row in self.store.pending():
            try:
                self.provider(row)
            except Exception as error:
                self.store.outcome(row['id'], False, error, row['token'])
                # Never log provider error payloads: they may echo registration tokens.
                logging.warning('Native push failed (%s); retry saved.', reason(error))
            else:
                self.store.outcome(row['id'], True)

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as error:
                logging.warning('Native push delivery failed (%s).', type(error).__name__)
            self.stop.wait(self.interval)

    def start(self):
        self.thread = threading.Thread(target=self.run, name='native-phone-push', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=12)


def mobile_push_router(store):
    api = APIRouter(prefix='/groceries/v1/mobile')

    def device(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith('Bearer pa_mobile_'):
            raise HTTPException(401, 'Pair the companion app.')
        try:
            return store.devices.authenticate(authorization[7:])
        except ValueError as error:
            raise HTTPException(401, str(error)) from None

    class Registration(BaseModel):
        model_config = ConfigDict(extra='forbid')
        provider: str = Field(pattern=r'^fcm$')
        token: str = Field(min_length=50, max_length=4096)

    class Receipt(BaseModel):
        model_config = ConfigDict(extra='forbid')
        cursor: int = Field(ge=0)

    class Snooze(BaseModel):
        model_config = ConfigDict(extra='forbid')
        id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
        seconds: int = Field(default=600, ge=60, le=3600)

    @api.post('/push/register')
    def register(body: Registration, phone=Depends(device)):
        return store.register(phone, body.provider, body.token)

    @api.post('/push/unregister')
    def unregister(phone=Depends(device)):
        store.unregister(phone)
        return {'registered': False}

    @api.get('/push/status')
    def status(phone=Depends(device)):
        return store.status(phone)

    @api.get('/events')
    def events(cursor: int = Query(default=0, ge=0), phone=Depends(device)):
        return store.events(phone, cursor)

    @api.post('/events/receipt')
    def receipt(body: Receipt, phone=Depends(device)):
        return store.receipt(phone, body.cursor)

    @api.post('/events/{identifier}/snooze')
    def snooze(identifier: str, body: Snooze, phone=Depends(device)):
        return store.snooze(phone, body.id, identifier, body.seconds)

    @api.websocket('/events/live')
    async def event_stream(ws: WebSocket, cursor: int = 0):
        try:
            phone = device(ws.headers.get('authorization'))
            if cursor < 0:
                raise ValueError()
        except (HTTPException, ValueError):
            await ws.close(code=4401)
            return
        await ws.accept()
        await ws.send_json({'type': 'ready'})
        heartbeat = 0
        try:
            while store.active(phone):
                result = store.events(phone, cursor)
                if result['items']:
                    await ws.send_json({'type': 'events', **result})
                    cursor = result['next_cursor']
                elif heartbeat % 20 == 0:
                    await ws.send_json({'type': 'keepalive'})
                heartbeat += 1
                await asyncio.sleep(1)
            await ws.close(code=4401)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass

    return api
