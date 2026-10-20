"""Read-only calendar view for the phone, and the queue of entries added on the phone.

The laptop calendar stays the only writer. It publishes its upcoming entries here; the phone reads them with
each reminder's cloud delivery state, and entries added on the phone wait here until the laptop applies them.
"""
from contextlib import contextmanager
from datetime import date
import json
from pathlib import Path
import re
import sqlite3
import time

KEEP_RESOLVED = 7 * 86400


class CalendarFeed:
    def __init__(self, path, reminders=None, clock=time.time):
        self.path, self.reminders, self.clock = Path(path), reminders, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS agenda (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending', 'added', 'failed')),
                    detail TEXT NOT NULL DEFAULT '', event_id TEXT, updated REAL NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def publish(self, agenda):
        if not isinstance(agenda.get('events'), list) or len(agenda['events']) > 5000:
            raise ValueError('Invalid calendar agenda.')
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO agenda VALUES (1,?,?)', (json.dumps(agenda), self.clock()))
        return {'count': len(agenda['events'])}

    def view(self):
        """The published agenda with each reminder's state: scheduled, sent or missing from the cloud."""
        with self.connection() as db:
            row = db.execute('SELECT * FROM agenda').fetchone()
            db.execute("DELETE FROM requests WHERE state!='pending' AND updated<?", (self.clock() - KEEP_RESOLVED,))
            requests = [self._request(r) for r in db.execute('SELECT * FROM requests ORDER BY created')]
        agenda = json.loads(row['payload']) if row else {'events': []}
        states = self.reminders.states() if self.reminders else None
        for event in agenda['events']:
            for reminder in event.get('reminders', []):
                state = (states or {}).get(reminder['id'])
                reminder['state'] = ('sent' if reminder.get('delivered_at') or state == 'accepted' else
                                     'scheduled' if state == 'pending' else 'unknown' if states is None else 'missing')
        return {**agenda, 'published': row['updated'] if row else None, 'requests': requests}

    @staticmethod
    def _request(row):
        return {**json.loads(row['payload']), 'id': row['id'], 'state': row['state'], 'detail': row['detail'],
                'event_id': row['event_id'], 'created': row['created']}

    def request(self, body):
        """Queue an entry added on the phone; repeating the same request ID returns the original."""
        identifier = body['id']
        payload = {k: body.get(k) for k in ('title', 'date', 'start', 'end', 'all_day', 'kind')}
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM requests WHERE id=?', (identifier,)).fetchone()
            if existing:
                return self._request(existing)
            if db.execute("SELECT COUNT(*) FROM requests WHERE state='pending'").fetchone()[0] >= 50:
                raise ValueError('Too many entries are waiting for the laptop.')
            db.execute('INSERT INTO requests(id,payload,created,state,updated) VALUES (?,?,?,?,?)',
                       (identifier, json.dumps(payload), self.clock(), 'pending', self.clock()))
            return self._request(db.execute('SELECT * FROM requests WHERE id=?', (identifier,)).fetchone())

    def pending(self):
        with self.connection() as db:
            return [self._request(r) for r in db.execute("SELECT * FROM requests WHERE state='pending' ORDER BY created")]

    def resolve(self, identifier, added, detail='', event_id=None):
        with self.connection() as db:
            changed = db.execute("UPDATE requests SET state=?,detail=?,event_id=?,updated=? WHERE id=? AND state='pending'",
                                 ('added' if added else 'failed', detail[:300], event_id, self.clock(), identifier)).rowcount
        return {'resolved': bool(changed)}


def validate(body):
    """Phone entries: a title and a day, either all day (optionally a yearly birthday) or with start and end times."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', body.id):
        raise ValueError('Invalid request ID.')
    date.fromisoformat(body.date)
    if body.kind == 'birthday' and not body.all_day:
        raise ValueError('A birthday is an all-day entry.')
    if not body.all_day:
        if not (body.start and body.end and re.fullmatch(r'\d\d:\d\d', body.start) and re.fullmatch(r'\d\d:\d\d', body.end)):
            raise ValueError('Timed entries need a start and end time.')
        if body.end <= body.start:
            raise ValueError('The end must be after the start.')


def calendar_router(feed, worker_auth, device_auth=None):
    from fastapi import APIRouter, Depends, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, ConfigDict, Field

    class Resolution(BaseModel):
        model_config = ConfigDict(extra='forbid')
        added: bool
        detail: str = Field(default='', max_length=300)
        event_id: str | None = Field(default=None, max_length=64)

    class Entry(BaseModel):
        model_config = ConfigDict(extra='forbid')
        id: str = Field(min_length=8, max_length=64)
        title: str = Field(min_length=1, max_length=200)
        date: str = Field(max_length=10)
        start: str | None = Field(default=None, max_length=5)
        end: str | None = Field(default=None, max_length=5)
        all_day: bool = False
        kind: str = Field(default='event', pattern='^(event|birthday)$')

    laptop = APIRouter(prefix='/v1/calendar', dependencies=[Depends(worker_auth)])

    @laptop.put('/agenda')
    def publish(body: dict):
        try:
            return feed.publish(body)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @laptop.get('/requests')
    def pending():
        return {'requests': feed.pending()}

    @laptop.post('/requests/{identifier}')
    def resolve(identifier: str, body: Resolution):
        return feed.resolve(identifier, body.added, body.detail, body.event_id)

    routers = [laptop]
    if device_auth:
        phone = APIRouter(prefix='/groceries/v1/mobile/calendar', dependencies=[Depends(device_auth)])

        @phone.get('')
        def view():
            return JSONResponse(feed.view(), headers={'Cache-Control': 'private, no-store'})

        @phone.post('/requests')
        def add(body: Entry):
            try:
                validate(body)
                return feed.request({**body.model_dump(), 'title': body.title.strip()})
            except ValueError as error:
                raise HTTPException(422, str(error)) from None

        routers.append(phone)
    return routers
