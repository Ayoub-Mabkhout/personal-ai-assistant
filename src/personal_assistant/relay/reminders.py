"""Durable projection of local calendar reminders and laptop-independent delivery."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from uuid import UUID
from zoneinfo import ZoneInfo


def epoch(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Reminder timestamps require an explicit UTC offset.')
    return parsed.timestamp()


class ReminderStore:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS projection (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    source_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY, event_id TEXT NOT NULL, payload TEXT NOT NULL,
                    due REAL NOT NULL, expires REAL NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', accepted REAL,
                    attempts INTEGER NOT NULL DEFAULT 0, retry_after REAL NOT NULL DEFAULT 0,
                    lease_until REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY, id TEXT NOT NULL, kind TEXT NOT NULL,
                    at REAL NOT NULL, detail TEXT NOT NULL
                );
            ''')
            if 'lease_until' not in {row['name'] for row in db.execute('PRAGMA table_info(reminders)')}:
                db.execute('ALTER TABLE reminders ADD COLUMN lease_until REAL NOT NULL DEFAULT 0')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _audit(self, db, identifier, kind, detail=None):
        db.execute('INSERT INTO audit(id,kind,at,detail) VALUES (?,?,?,?)',
                   (identifier, kind, self.clock(), json.dumps(detail or {})))

    def project(self, snapshot):
        source, revision, rows = snapshot['source_id'], snapshot['revision'], snapshot['reminders']
        UUID(source)
        if type(revision) is not int or revision < 0 or len(rows) > 5000:
            raise ValueError('Invalid reminder snapshot revision or size.')
        validated = {}
        for row in rows:
            UUID(row['id']); UUID(row['event_id']); ZoneInfo(row['timezone'])
            if row['id'] in validated or not row['title'].strip() or len(row['title']) > 1000:
                raise ValueError('Duplicate reminder or invalid title.')
            due, start, expires = epoch(row['due_at']), epoch(row['start_utc']), epoch(row['end_utc'])
            if due > start or expires <= start or type(row['lead_minutes']) is not int or row['lead_minutes'] < 0:
                raise ValueError('Invalid reminder times or lead.')
            payload = json.dumps(row, sort_keys=True, separators=(',', ':'))
            validated[row['id']] = (row, payload, due, expires)
        canonical = json.dumps({'source_id': source, 'revision': revision,
                                'reminders': sorted(rows, key=lambda row: row['id'])}, sort_keys=True)
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM projection').fetchone()
            if previous:
                if previous['source_id'] != source:
                    raise ValueError('Reminder projection belongs to another calendar.')
                if revision < previous['revision']:
                    raise ValueError('Stale reminder snapshot; restore requires explicit reconciliation.')
                if revision == previous['revision']:
                    if fingerprint != previous['fingerprint']:
                        raise ValueError('Same reminder revision has different contents.')
                    return {'revision': revision, 'changed': False, 'count': len(rows)}
            current = {row['id']: row for row in db.execute('SELECT * FROM reminders')}
            for identifier, (row, payload, due, expires) in validated.items():
                old = current.get(identifier)
                # An occurrence ID must not be reused for a different event/time.
                if old and (old['event_id'] != row['event_id'] or old['due'] != due):
                    raise ValueError('Reminder occurrence ID was reused with different times.')
                if old:
                    db.execute('UPDATE reminders SET payload=?,expires=? WHERE id=?', (payload, expires, identifier))
                else:
                    accepted = epoch(row['delivered_at']) if row.get('delivered_at') else None
                    db.execute('INSERT INTO reminders(id,event_id,payload,due,expires,state,accepted) VALUES (?,?,?,?,?,?,?)',
                        (identifier, row['event_id'], payload, due, expires, 'accepted' if accepted is not None else 'pending', accepted))
                    self._audit(db, identifier, 'projected')
            for identifier in set(current) - set(validated):
                db.execute('DELETE FROM reminders WHERE id=?', (identifier,))
                self._audit(db, identifier, 'removed')
            db.execute('INSERT OR REPLACE INTO projection VALUES (1,?,?,?,?)', (source, revision, fingerprint, self.clock()))
        return {'revision': revision, 'changed': True, 'count': len(rows)}

    def due(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('''SELECT * FROM reminders
                WHERE state='pending' AND due<=? AND expires>? AND retry_after<=? AND lease_until<=? ORDER BY due,id''',
                (self.clock(), self.clock(), self.clock(), self.clock()))]

    def claim(self, identifier, payload):
        with self.connection() as db:
            changed = db.execute('''UPDATE reminders SET lease_until=? WHERE id=? AND payload=?
                AND state='pending' AND due<=? AND expires>? AND retry_after<=? AND lease_until<=?''',
                (self.clock()+30, identifier, payload, self.clock(), self.clock(), self.clock(), self.clock())).rowcount
        return bool(changed)

    def current(self, identifier, payload):
        with self.connection() as db:
            row = db.execute('SELECT * FROM reminders WHERE id=?', (identifier,)).fetchone()
            return bool(row and row['state'] == 'pending' and row['payload'] == payload and
                        row['due'] <= self.clock() < row['expires'] and row['retry_after'] <= self.clock())

    def accepted(self, identifier, payload):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE reminders SET state='accepted',accepted=?,lease_until=0 WHERE id=? AND payload=? AND state='pending'",
                                 (self.clock(), identifier, payload)).rowcount
            if changed:
                self._audit(db, identifier, 'phone_notification_accepted')
        return bool(changed)

    def failed(self, identifier, payload, error_kind):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT attempts FROM reminders WHERE id=? AND payload=? AND state='pending'", (identifier, payload)).fetchone()
            if row:
                attempts = row['attempts'] + 1
                db.execute('UPDATE reminders SET attempts=?,retry_after=?,lease_until=0 WHERE id=?',
                           (attempts, self.clock() + min(300, 2 ** min(attempts, 8)), identifier))
                self._audit(db, identifier, 'push_failed', {'error': error_kind})

    def receipts(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT id,accepted FROM reminders WHERE state='accepted' ORDER BY id")]

    def status(self):
        with self.connection() as db:
            projection = db.execute('SELECT source_id,revision,updated FROM projection').fetchone()
            counts = {row['state']: row['n'] for row in db.execute('SELECT state,COUNT(*) n FROM reminders GROUP BY state')}
        return {'projection': dict(projection) if projection else None, 'counts': counts}


class ReminderPump:
    def __init__(self, store, sender, interval=5, visibility='private'):
        self.store, self.sender, self.interval, self.visibility = store, sender, interval, visibility
        self.stop = threading.Event()
        self.thread = None

    def tick(self):
        for row in self.store.due():
            if not self.store.claim(row['id'], row['payload']) or not self.store.current(row['id'], row['payload']):
                continue
            reminder = json.loads(row['payload'])
            local = datetime.fromisoformat(reminder['start_utc']).astimezone(ZoneInfo(reminder['timezone']))
            when = local.strftime('%a %d %b, %H:%M') if not reminder['all_day'] else local.strftime('%a %d %b')
            message = reminder['title'] + '\n' + when
            if reminder.get('location'):
                message += '\n' + reminder['location']
            remaining = max(1, int(row['expires'] - self.store.clock()))
            payload = {'title': 'Calendar reminder', 'message': message,
                       'data': {'tag': 'assistant-calendar-' + row['id'], 'group': 'assistant-calendar',
                                'channel': 'Calendar reminders', 'priority': 'high',
                                'ttl': min(86400, remaining), 'visibility': self.visibility}}
            try:
                self.sender(payload)
            except Exception as error:
                self.store.failed(row['id'], row['payload'], type(error).__name__)
                logging.warning('Calendar reminder push failed (%s); retry saved.', type(error).__name__)
            else:
                self.store.accepted(row['id'], row['payload'])

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as error:
                logging.warning('Calendar reminder poll failed (%s).', type(error).__name__)
            self.stop.wait(self.interval)

    def start(self):
        self.thread = threading.Thread(target=self.run, name='calendar-reminders', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=12)


def reminder_router(store, submit_auth, worker_auth):
    """Sync/receipts use the laptop worker credential; owner can query sync status."""
    from fastapi import APIRouter, Depends
    from pydantic import BaseModel, ConfigDict, Field

    class Reminder(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        id: str
        event_id: str
        lead_minutes: int = Field(ge=0)
        due_at: str
        delivered_at: str | None = None
        title: str = Field(min_length=1, max_length=1000)
        start_utc: str
        end_utc: str
        timezone: str
        all_day: int | bool
        location: str = Field(max_length=4000)

    class Snapshot(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        source_id: str
        revision: int = Field(ge=0)
        reminders: list[Reminder] = Field(max_length=5000)

    router = APIRouter()

    @router.post('/v1/calendar/reminders/snapshot', dependencies=[Depends(worker_auth)])
    def snapshot(value: Snapshot):
        return store.project(value.model_dump())

    @router.get('/v1/calendar/reminders/receipts', dependencies=[Depends(worker_auth)])
    def receipts():
        return {'receipts': store.receipts()}

    @router.get('/v1/calendar/reminders/status', dependencies=[Depends(submit_auth)])
    def status():
        return store.status()

    return router
