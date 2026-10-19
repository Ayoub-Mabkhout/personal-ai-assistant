"""Open-banking redirect catcher and the phone's view of the money summary.

The laptop holds the provider key and the ledger. The relay only (1) receives the bank's
redirect for a consent the laptop announced beforehand and keeps its one-time code until
the laptop collects it, and (2) stores the laptop's latest summary so the paired phone can
show it over mobile data, plus the owner's answers to review questions for the laptop to
collect. No transaction history is kept here beyond what that summary shows.
"""
from contextlib import contextmanager
from datetime import date, datetime, time as day_time, timedelta
import hashlib
import base64
import struct
import html
import json
import logging
from pathlib import Path
import re
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

STATE = r'^[A-Za-z0-9_-]{16,64}$'
PENDING_SECONDS = 1800
SUMMARY_LIMIT = 2 * 1024 * 1024
REMINDER_ZONE = ZoneInfo('Europe/Berlin')


class Pending(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    state: str = Field(pattern=STATE)


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    transaction: str = Field(min_length=1, max_length=200)
    choice: str = Field(min_length=1, max_length=60)
    note: str = Field(default='', max_length=4000)


class Ack(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    through: int = Field(ge=0)


class ConversationQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    text: str = Field(min_length=1, max_length=4000)


class ConversationAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(min_length=1, max_length=12000)


def page(title, text):
    return HTMLResponse('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title><body style="font-family:system-ui,sans-serif;background:#130E1C;color:#EDE6F7;display:grid;place-items:center;'
        'min-height:90vh;margin:0;text-align:center"><div style="max-width:22rem;padding:1rem"><h1 style="font-weight:500;font-size:1.4rem">%s</h1>'
        '<p style="color:#A898BF">%s</p></div>' % (html.escape(title), html.escape(title), html.escape(text)))


class Banking:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        with db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS pending(state TEXT PRIMARY KEY,expires REAL NOT NULL,code TEXT,error TEXT,returned REAL);
            CREATE TABLE IF NOT EXISTS summary(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS answers(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,body TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS consent_reminders(bank TEXT PRIMARY KEY,valid_until TEXT NOT NULL,
                due REAL NOT NULL,expires REAL NOT NULL,accepted REAL,attempts INTEGER NOT NULL DEFAULT 0,
                retry_after REAL NOT NULL DEFAULT 0,lease_until REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,text TEXT NOT NULL,created REAL NOT NULL,
                collected REAL,answer TEXT,answered REAL);
            CREATE TABLE IF NOT EXISTS merchant_logo_assets(id TEXT PRIMARY KEY,png BLOB NOT NULL);''')
        db.close()

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        finally:
            db.close()

    def logo(self, identity):
        if not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise HTTPException(404, 'Logo not found')
        with self.db() as db:
            row = db.execute('SELECT png FROM merchant_logo_assets WHERE id=?', (identity,)).fetchone()
        if not row:
            raise HTTPException(404, 'Logo not found')
        return Response(row[0], media_type='image/png', headers={
            'Cache-Control': 'private, max-age=31536000, immutable', 'ETag': '"'+identity+'"',
            'X-Content-Type-Options': 'nosniff'})

    def expect(self, state):
        now = self.clock()
        with self.db() as db:
            db.execute('DELETE FROM pending WHERE expires<?', (now,))
            db.execute('INSERT OR REPLACE INTO pending(state,expires) VALUES(?,?)', (state, now + PENDING_SECONDS))
        return {'state': state, 'expires': now + PENDING_SECONDS}

    def returned(self, state, code, error):
        """Records the bank's redirect once; an unknown, expired or repeated state is refused."""
        with self.db() as db:
            row = db.execute('SELECT returned FROM pending WHERE state=? AND expires>=?', (state, self.clock())).fetchone()
            if not row or row[0] is not None:
                return False
            db.execute('UPDATE pending SET code=?,error=?,returned=? WHERE state=?', (code, error, self.clock(), state))
        return True

    def collect(self, state):
        with self.db() as db:
            row = db.execute('SELECT code,error,returned,expires FROM pending WHERE state=?', (state,)).fetchone()
            if not row or row[3] < self.clock():
                raise HTTPException(404, 'No consent is waiting under that state.')
            if row[2] is None:
                return {'status': 'waiting'}
            # The code is handed over once.
            db.execute('DELETE FROM pending WHERE state=?', (state,))
        return {'status': 'error', 'error': row[1]} if row[1] or not row[0] else {'status': 'returned', 'code': row[0]}

    def publish(self, body):
        body = dict(body)
        assets = {}
        logos = body.get('merchant_logos', {})
        if not isinstance(logos, dict) or len(logos) > 256:
            raise ValueError('Invalid merchant logo catalog')
        descriptors = {}
        for merchant, value in logos.items():
            if not isinstance(merchant, str) or not 1 <= len(merchant) <= 120 or not isinstance(value, str) or not value.startswith('data:image/png;base64,') or len(value) > 44000:
                raise ValueError('Invalid cached merchant logo')
            try:
                png = base64.b64decode(value[22:], validate=True)
                if len(png) > 32768 or len(png) < 33 or png[:8] != b'\x89PNG\r\n\x1a\n' or png[12:16] != b'IHDR': raise ValueError()
                width, height = struct.unpack('>II', png[16:24])
                if not 8 <= width <= 256 or not 8 <= height <= 256: raise ValueError()
            except (ValueError, struct.error):
                raise ValueError('Invalid PNG merchant logo') from None
            identity = hashlib.sha256(png).hexdigest()
            assets[identity] = png
            descriptors[merchant] = {'cache_id': identity, 'url': '/groceries/v1/mobile/money/logos/' + identity}
        if 'merchant_logos' in body:
            body['merchant_logos'] = descriptors
        text = json.dumps(body, separators=(',', ':'), ensure_ascii=False)
        if len(text.encode('utf-8')) > SUMMARY_LIMIT:
            raise ValueError('Summary is too large.')
        projected = None
        if 'banks' in body:
            if not isinstance(body['banks'], list) or len(body['banks']) > 100:
                raise ValueError('Invalid bank consent projection.')
            projected = {}
            for item in body['banks']:
                if not isinstance(item, dict) or not isinstance(item.get('bank'), str) or not 1 <= len(item['bank']) <= 100:
                    raise ValueError('Invalid bank consent projection.')
                bank, expiry = item['bank'], item.get('valid_until')
                if bank in projected:
                    raise ValueError('Duplicate bank consent.')
                if expiry is None:
                    continue
                try:
                    valid = date.fromisoformat(expiry)
                    if valid.isoformat() != expiry:
                        raise ValueError()
                except (TypeError, ValueError):
                    raise ValueError('Invalid bank consent expiry.') from None
                due = datetime.combine(valid - timedelta(days=14), day_time(9), REMINDER_ZONE).timestamp()
                end = datetime.combine(valid, day_time.min, REMINDER_ZONE).timestamp()
                projected[bank] = (expiry, due, end)
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO summary VALUES(1,?,?)', (text, self.clock()))
            db.executemany('INSERT OR IGNORE INTO merchant_logo_assets VALUES(?,?)', assets.items())
            if projected is not None:
                for bank, (expiry, due, end) in projected.items():
                    db.execute('''INSERT INTO consent_reminders(bank,valid_until,due,expires) VALUES(?,?,?,?)
                        ON CONFLICT(bank) DO UPDATE SET valid_until=excluded.valid_until,due=excluded.due,
                        expires=excluded.expires,accepted=CASE WHEN valid_until=excluded.valid_until THEN accepted ELSE NULL END,
                        attempts=CASE WHEN valid_until=excluded.valid_until THEN attempts ELSE 0 END,
                        retry_after=CASE WHEN valid_until=excluded.valid_until THEN retry_after ELSE 0 END,
                        lease_until=CASE WHEN valid_until=excluded.valid_until THEN lease_until ELSE 0 END''',
                        (bank, expiry, due, end))
                if projected:
                    db.execute('DELETE FROM consent_reminders WHERE bank NOT IN (%s)' % ','.join('?' * len(projected)), tuple(projected))
                else:
                    db.execute('DELETE FROM consent_reminders')
        return {'ok': True}

    def summary(self):
        with self.db() as db:
            row = db.execute('SELECT body,updated FROM summary WHERE id=1').fetchone()
        return {'summary': json.loads(row[0]) if row else None, 'received': row[1] if row else None}

    def answer(self, answer):
        encoded = answer.model_dump_json()
        with self.db() as db:
            existing = db.execute('SELECT body FROM answers WHERE id=?', (answer.id,)).fetchone()
            if existing and existing[0] != encoded:
                raise HTTPException(409, 'Answer ID already has different contents.')
            if not existing:
                db.execute('INSERT INTO answers(id,body,created) VALUES(?,?,?)', (answer.id, encoded, self.clock()))
        return {'ok': True}

    def answers(self):
        with self.db() as db:
            rows = db.execute('SELECT sequence,body FROM answers ORDER BY sequence LIMIT 200').fetchall()
        return {'items': [dict(json.loads(body), sequence=sequence) for sequence, body in rows]}

    def acknowledge(self, through):
        with self.db() as db:
            db.execute('DELETE FROM answers WHERE sequence<=?', (through,))
        return {'ok': True}

    def reminder_status(self):
        with self.db() as db:
            rows = db.execute('SELECT bank,valid_until,due,accepted,attempts FROM consent_reminders ORDER BY bank').fetchall()
        return {'projected': [{'bank': bank, 'valid_until': expiry, 'due': due,
                                'native_event_queued_at': accepted, 'attempts': attempts} for bank, expiry, due, accepted, attempts in rows],
                'handset_delivery_verified': False}

    def claim_reminder(self):
        now = self.clock()
        with self.db() as db:
            row = db.execute('''SELECT bank,valid_until,due,expires FROM consent_reminders
                WHERE accepted IS NULL AND due<=? AND expires>? AND retry_after<=? AND lease_until<=?
                ORDER BY due,bank LIMIT 1''', (now, now, now, now)).fetchone()
            if row:
                db.execute('UPDATE consent_reminders SET lease_until=? WHERE bank=? AND valid_until=?', (now + 30, row[0], row[1]))
        return row

    def reminder_current(self, bank, expiry):
        with self.db() as db:
            row = db.execute('SELECT 1 FROM consent_reminders WHERE bank=? AND valid_until=? AND accepted IS NULL AND expires>?',
                             (bank, expiry, self.clock())).fetchone()
        return bool(row)

    def finish_reminder(self, bank, expiry, error=None):
        with self.db() as db:
            if error is None:
                db.execute('''UPDATE consent_reminders SET accepted=?,lease_until=0
                    WHERE bank=? AND valid_until=? AND accepted IS NULL''', (self.clock(), bank, expiry))
            else:
                row = db.execute('SELECT attempts FROM consent_reminders WHERE bank=? AND valid_until=? AND accepted IS NULL',
                                 (bank, expiry)).fetchone()
                if row:
                    attempts = row[0] + 1
                    db.execute('''UPDATE consent_reminders SET attempts=?,retry_after=?,lease_until=0
                        WHERE bank=? AND valid_until=?''', (attempts, self.clock() + min(300, 2 ** min(attempts, 8)), bank, expiry))

    def ask(self, question):
        with self.db() as db:
            row = db.execute('SELECT text FROM conversations WHERE id=?', (question.id,)).fetchone()
            if row and row[0] != question.text:
                raise HTTPException(409, 'Conversation ID already has different text.')
            if not row:
                db.execute('INSERT INTO conversations(id,text,created) VALUES(?,?,?)',
                           (question.id, question.text, self.clock()))
        return self.conversation(question.id)

    def conversation(self, identifier):
        with self.db() as db:
            row = db.execute('SELECT id,text,created,answer,answered FROM conversations WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise HTTPException(404, 'Conversation not found.')
        return dict(zip(('id', 'text', 'created', 'answer', 'answered'), row))

    def conversations(self, limit=50, before=None):
        with self.db() as db:
            boundary = db.execute('SELECT created,id FROM conversations WHERE id=?', (before,)).fetchone() if before else None
            if before and not boundary:
                raise HTTPException(422, 'Invalid conversation cursor.')
            rows = db.execute('SELECT id FROM conversations '+('WHERE (created,id)<(?,?) ' if boundary else '')+
                              'ORDER BY created DESC,id DESC LIMIT ?', (*tuple(boundary), limit+1) if boundary else (limit+1,)).fetchall()
        return {'items': [self.conversation(row[0]) for row in rows[:limit]],
                'next_cursor': rows[limit-1][0] if len(rows)>limit else ''}

    def pending_conversations(self):
        with self.db() as db:
            rows = db.execute('SELECT id,text,created FROM conversations WHERE collected IS NULL ORDER BY created,id LIMIT 100').fetchall()
        return {'items': [dict(zip(('id', 'text', 'created'), row)) for row in rows]}

    def unanswered_conversations(self, after=None):
        with self.db() as db:
            boundary = db.execute('SELECT created,id FROM conversations WHERE id=?', (after,)).fetchone() if after else None
            if after and not boundary:
                raise HTTPException(422, 'Invalid conversation cursor.')
            rows = db.execute('''SELECT id,text,created FROM conversations WHERE answer IS NULL
                AND (created,id)>(?,?) ORDER BY created,id LIMIT 100''',
                tuple(boundary) if boundary else (0, '')).fetchall()
        return {'items': [dict(zip(('id', 'text', 'created'), row)) for row in rows]}

    def collect_conversation(self, identifier):
        with self.db() as db:
            if not db.execute('SELECT 1 FROM conversations WHERE id=?', (identifier,)).fetchone():
                raise HTTPException(404, 'Conversation not found.')
            db.execute('UPDATE conversations SET collected=COALESCE(collected,?) WHERE id=?', (self.clock(), identifier))
        return {'ok': True}

    def reply(self, identifier, answer):
        with self.db() as db:
            row = db.execute('SELECT answer FROM conversations WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise HTTPException(404, 'Conversation not found.')
            if row[0] is not None and row[0] != answer.text:
                raise HTTPException(409, 'Conversation already has a different answer.')
            db.execute('UPDATE conversations SET answer=?,answered=COALESCE(answered,?) WHERE id=?',
                       (answer.text, self.clock(), identifier))
        return self.conversation(identifier)


class ConsentReminderPump:
    def __init__(self, banking, sender, interval=60, visibility='private'):
        self.banking, self.sender, self.interval, self.visibility = banking, sender, interval, visibility
        self.stop = threading.Event()
        self.thread = None

    def tick(self):
        while row := self.banking.claim_reminder():
            bank, expiry = row[0], row[1]
            if not self.banking.reminder_current(bank, expiry):
                continue
            # The calendar tag selects Companion's native reminder event, with a stable
            # identity so a retry replaces the same notification on the handset.
            payload = {'title': 'Renew Money access',
                       'message': '%s read-only access expires on %s. Open Money to renew it.' % (bank, expiry),
                       'data': {'tag': 'assistant-calendar-money-consent-' + hashlib.sha256(bank.encode()).hexdigest()[:16] + '-' + expiry,
                                'group': 'assistant-money', 'channel': 'Money reminders', 'priority': 'high',
                                'notification_icon': 'mdi:bank-clock', 'visibility': self.visibility,
                                'ttl': min(86400, max(1, int(row[3] - self.banking.clock())))}}
            try:
                self.sender(payload)
            except Exception as error:
                self.banking.finish_reminder(bank, expiry, error=type(error).__name__)
                logging.warning('Money consent reminder push failed (%s); retry saved.', type(error).__name__)
            else:
                self.banking.finish_reminder(bank, expiry)

    def run(self):
        while not self.stop.is_set():
            try: self.tick()
            except Exception as error: logging.warning('Money consent reminder poll failed (%s).', type(error).__name__)
            self.stop.wait(self.interval)

    def start(self):
        self.thread = threading.Thread(target=self.run, name='money-consent-reminders', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=12)


def banking_router(banking, submit, device, owner_auth=None):
    owner = APIRouter(prefix='/v1/banking', dependencies=[Depends(submit)])
    public = APIRouter()
    phone = APIRouter(prefix='/groceries/v1/mobile/money', dependencies=[Depends(device)])
    conversation = APIRouter(prefix='/v1/banking/conversations')
    owner_view = APIRouter(prefix='/v1/banking')

    def authorize(request: Request, authorization: str | None):
        if owner_auth:
            owner_auth.authorize(request, authorization)
        else:
            submit(authorization)

    @owner.post('/pending')
    def expect(body: Pending):
        return banking.expect(body.state)

    @owner.get('/pending/{state}')
    def collect(state: str):
        return banking.collect(state)

    @owner.put('/summary')
    def publish(body: dict):
        return banking.publish(body)

    @owner.get('/answers')
    def answers():
        return banking.answers()

    @owner.post('/answers/ack')
    def acknowledge(body: Ack):
        return banking.acknowledge(body.through)

    @owner_view.get('/summary')
    def owner_summary(request: Request, authorization: str | None = Header(default=None)):
        authorize(request, authorization)
        return JSONResponse(banking.summary(), headers={'Cache-Control': 'private, no-store'})

    @owner_view.get('/logos/{identity}')
    def owner_logo(identity: str, request: Request, authorization: str | None = Header(default=None)):
        authorize(request, authorization)
        return banking.logo(identity)

    @owner_view.get('/reminders/status')
    def reminder_status(request: Request, authorization: str | None = Header(default=None)):
        authorize(request, authorization)
        return banking.reminder_status()

    @conversation.get('')
    def owner_conversations(request: Request, authorization: str | None = Header(default=None)):
        authorize(request, authorization)
        return banking.conversations()

    @conversation.post('')
    def owner_question(body: ConversationQuestion, request: Request, authorization: str | None = Header(default=None)):
        authorize(request, authorization)
        return banking.ask(body)

    @conversation.get('/pending', dependencies=[Depends(submit)])
    def pending_conversations():
        return banking.pending_conversations()

    @conversation.get('/unanswered', dependencies=[Depends(submit)])
    def unanswered_conversations(after: str | None = Query(default=None, pattern=r'^[A-Za-z0-9_-]{8,64}$')):
        return banking.unanswered_conversations(after)

    @conversation.get('/{identifier}')
    def owner_conversation(identifier: str, request: Request, authorization: str | None = Header(default=None)):
        authorize(request, authorization)
        return banking.conversation(identifier)

    @conversation.post('/{identifier}/ack', dependencies=[Depends(submit)])
    def collect_conversation(identifier: str):
        return banking.collect_conversation(identifier)

    @conversation.put('/{identifier}/answer', dependencies=[Depends(submit)])
    def reply(identifier: str, body: ConversationAnswer):
        return banking.reply(identifier, body)

    @public.get('/v1/banking/callback', include_in_schema=False)
    def callback(state: str = Query(default='', max_length=64), code: str = Query(default='', max_length=2048),
                 error: str = Query(default='', max_length=200)):
        if not re.fullmatch(STATE, state) or not banking.returned(state, code or None, error or (None if code else 'no_code')):
            return page('Link expired', 'Start the bank link again from your assistant.')
        if error or not code:
            return page('Bank link cancelled', 'Nothing was shared. You can start again from your assistant.')
        return page('Bank linked', 'Your assistant is finishing the setup. You can close this page.')

    @phone.get('')
    def summary():
        return JSONResponse(banking.summary(), headers={'Cache-Control': 'private, no-store'})

    @phone.get('/logos/{identity}')
    def phone_logo(identity: str):
        return banking.logo(identity)

    @phone.post('/answers')
    def answer(body: Answer):
        return banking.answer(body)

    @phone.get('/conversations')
    def phone_conversations(before: str | None = Query(default=None, pattern=r'^[A-Za-z0-9_-]{8,64}$')):
        return banking.conversations(before=before)

    @phone.post('/conversations')
    def phone_question(body: ConversationQuestion):
        return banking.ask(body)

    @phone.get('/conversations/{identifier}')
    def phone_conversation(identifier: str):
        return banking.conversation(identifier)

    return owner, public, phone, conversation, owner_view
