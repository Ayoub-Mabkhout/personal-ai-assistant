"""Authenticated Companion replies become durable contextual agent prompts."""
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import Conflict, Missing, timestamp


ACTION_PREFIX = 'ASSISTANT_REPLY:'


def reply_action(kind, identifier):
    return ACTION_PREFIX + kind + ':' + identifier


class NotificationReply(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    event_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,128}$')
    action: str = Field(min_length=1, max_length=256)
    tag: str = Field(min_length=1, max_length=256)
    reply_text: str = Field(min_length=1, max_length=4096)
    time_fired: str = Field(min_length=1, max_length=100)

    @field_validator('reply_text')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Reply must contain text.')
        return value

    @field_validator('time_fired')
    @classmethod
    def explicit_time(cls, value):
        timestamp(value)
        return value


class ReplyInbox:
    """Persist immutable submission before queueing; recover either crash boundary.

    Event context IDs identify retries of one notification event. A genuinely new event, even
    with identical text, is a new instruction. No parent task is rerun or reopened.
    """
    def __init__(self, queues, path=None):
        self.queues = queues
        self.agents = queues['agent']
        self.path = Path(path or self.agents.path.with_name('notification-replies.sqlite3'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS replies (
                event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                payload TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0
            )''')
        self.recover_pending()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def mark_accepted(self, event_id):
        with self.connection() as db:
            db.execute('UPDATE replies SET accepted=1 WHERE event_id=?', (event_id,))

    def recover_pending(self):
        """Startup recovery covers a crash before or after the queue transaction."""
        with self.connection() as db:
            rows = db.execute('SELECT event_id,payload FROM replies WHERE accepted=0 ORDER BY rowid').fetchall()
        for event_id, encoded in rows:
            self.agents.submit(json.loads(encoded), source='notification_reply')
            self.mark_accepted(event_id)

    def accept(self, event):
        raw = event.model_dump()
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        match = re.fullmatch(r'ASSISTANT_REPLY:(agent|command):([A-Za-z0-9_-]{8,64})', event.action)
        if not match:
            raise ValueError('Not an assistant task reply.')
        kind, identifier = match.groups()
        if event.tag != 'assistant-' + kind + '-' + identifier:
            raise ValueError('Reply action does not match its notification.')
        if kind not in self.queues:
            raise ValueError('Unknown queue.')
        # The receipt payload is immutable even if the parent completes while delivery
        # retries. Queue.submit uses this exact envelope again after a crash.
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT fingerprint,payload FROM replies WHERE event_id=?', (event.event_id,)).fetchone()
            if row:
                if row[0] != digest:
                    raise Conflict('This reply event ID already has different content.')
                payload = json.loads(row[1])
            else:
                parent = self.queues[kind].get(identifier)
                if timestamp(event.time_fired) > self.agents.clock() + 300:
                    raise ValueError('Reply event time is too far in the future.')
                previous = parent['payload'].get('reply_context') or {}
                ancestry = list(previous.get('ancestry', []))[-15:] + [{'kind': kind, 'id': identifier}]
                context = {
                    'parent_kind': kind, 'parent_id': identifier,
                    'parent_state': parent['state'],
                    'original_request': previous.get('original_request', parent['payload']['command']),
                    'parent_request': parent['payload']['command'],
                    'parent_summary': (parent.get('result') or {}).get('summary', ''),
                    'ancestry': ancestry,
                }
                payload = {
                    'id': 'reply-' + hashlib.sha256(event.event_id.encode()).hexdigest()[:48],
                    'command': event.reply_text, 'timezone': parent['payload']['timezone'],
                    'created_at': event.time_fired, 'expires_at': None,
                    'workspace': parent['payload'].get('workspace'), 'reply_context': context,
                }
                db.execute('INSERT INTO replies(event_id,fingerprint,payload) VALUES(?,?,?)',
                           (event.event_id, digest, json.dumps(payload, sort_keys=True, ensure_ascii=False)))
        job, created = self.agents.submit(payload, source='notification_reply')
        self.mark_accepted(event.event_id)
        return job, created


def reply_router(queues, authorize, path=None):
    """`authorize` must be the relay service/owner credential dependency.

    Never pass the read-only task-view capability verifier here. Headless callers
    use their protected service secret, not a credential from the URL.
    """
    inbox = ReplyInbox(queues, path)
    api = APIRouter()

    @api.post('/v1/notification-replies', dependencies=[Depends(authorize)])
    def receive(event: NotificationReply):
        try:
            job, created = inbox.accept(event)
        except Missing as error:
            raise HTTPException(404, str(error)) from None
        except ValueError as error:
            if isinstance(error, Conflict):
                raise HTTPException(409, str(error)) from None
            raise HTTPException(422, str(error)) from None
        return JSONResponse({'job': job, 'created': created,
                             'connection': queues['agent'].status(),
                             'notifications': {'enabled': queues['agent'].notifications_enabled}},
                            status_code=201 if created else 200)

    return api
