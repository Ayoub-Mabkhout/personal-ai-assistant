"""Open-banking redirect catcher and the phone's view of the money summary.

The laptop holds the provider key and the ledger. The relay only (1) receives the bank's
redirect for a consent the laptop announced beforehand and keeps its one-time code until
the laptop collects it, and (2) stores the laptop's latest summary so the paired phone can
show it over mobile data, plus the owner's answers to review questions for the laptop to
collect. No transaction history is kept here beyond what that summary shows.
"""
from contextlib import contextmanager
import html
import json
from pathlib import Path
import re
import sqlite3
import time
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

STATE = r'^[A-Za-z0-9_-]{16,64}$'
PENDING_SECONDS = 1800
SUMMARY_LIMIT = 256 * 1024


class Pending(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    state: str = Field(pattern=STATE)


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    transaction: str = Field(min_length=1, max_length=200)
    choice: str = Field(min_length=1, max_length=60)
    note: str = Field(default='', max_length=500)


class Ack(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    through: int = Field(ge=0)


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
            CREATE TABLE IF NOT EXISTS answers(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,body TEXT NOT NULL,created REAL NOT NULL);''')
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
        text = json.dumps(body, separators=(',', ':'))
        if len(text) > SUMMARY_LIMIT:
            raise ValueError('Summary is too large.')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO summary VALUES(1,?,?)', (text, self.clock()))
        return {'ok': True}

    def summary(self):
        with self.db() as db:
            row = db.execute('SELECT body,updated FROM summary WHERE id=1').fetchone()
        return {'summary': json.loads(row[0]) if row else None, 'received': row[1] if row else None}

    def answer(self, answer):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO answers(id,body,created) VALUES(?,?,?)', (answer.id, answer.model_dump_json(), self.clock()))
        return {'ok': True}

    def answers(self):
        with self.db() as db:
            rows = db.execute('SELECT sequence,body FROM answers ORDER BY sequence LIMIT 200').fetchall()
        return {'items': [dict(json.loads(body), sequence=sequence) for sequence, body in rows]}

    def acknowledge(self, through):
        with self.db() as db:
            db.execute('DELETE FROM answers WHERE sequence<=?', (through,))
        return {'ok': True}


def banking_router(banking, submit, device):
    owner = APIRouter(prefix='/v1/banking', dependencies=[Depends(submit)])
    public = APIRouter()
    phone = APIRouter(prefix='/groceries/v1/mobile/money', dependencies=[Depends(device)])

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
        return banking.summary()

    @phone.post('/answers')
    def answer(body: Answer):
        return banking.answer(body)

    return owner, public, phone
