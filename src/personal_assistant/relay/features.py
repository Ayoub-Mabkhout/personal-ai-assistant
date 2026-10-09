"""Shared assistant features checklist, hosted on the relay for the phone and dashboard.

One SQLite store serves two mounts: the paired Companion over mobile data and the
laptop dashboard through the submit credential. Client-generated IDs make offline
creation replay-safe; deletions leave a tombstone so a late replay cannot revive them.
"""
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import time
from typing import Literal
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

ID = r'^[A-Za-z0-9_-]{8,64}$'
Area = Literal['companion', 'dashboard', 'assistant']


class Gone(ValueError):
    pass


class NewFeature(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str | None = Field(default=None, pattern=ID)
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default='', max_length=1000)
    area: Area = 'assistant'


class FeatureEdit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    done: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=1000)
    area: Area | None = None


def clean_title(value):
    title = ' '.join(value.split())
    if not title:
        raise ValueError('A feature needs a title.')
    return title


class Features:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS features(id TEXT PRIMARY KEY,title TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',
                area TEXT NOT NULL,done_at REAL,created REAL NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS deleted_features(id TEXT PRIMARY KEY,deleted REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS feature_meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
            INSERT OR IGNORE INTO feature_meta VALUES('revision',0);''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15); db.row_factory = sqlite3.Row
        try: yield db; db.commit()
        except BaseException: db.rollback(); raise
        finally: db.close()

    @staticmethod
    def item(row):
        return {'id': row['id'], 'title': row['title'], 'detail': row['detail'], 'area': row['area'],
                'done': row['done_at'] is not None, 'done_at': row['done_at'], 'created': row['created'], 'updated': row['updated']}

    @staticmethod
    def bump(db):
        db.execute("UPDATE feature_meta SET value=value+1 WHERE key='revision'")

    def snapshot(self):
        with self.db() as db:
            db.execute('BEGIN')
            revision = db.execute("SELECT value FROM feature_meta WHERE key='revision'").fetchone()[0]
            # Open items in the order they were planned; finished ones newest first.
            rows = db.execute('''SELECT * FROM features ORDER BY done_at IS NOT NULL,
                CASE WHEN done_at IS NULL THEN created ELSE -done_at END,rowid''')
            return {'revision': revision, 'items': [self.item(row) for row in rows]}

    def create(self, body):
        identifier = body.get('id') or str(uuid.uuid4())
        title, detail = clean_title(body['title']), body.get('detail', '').strip()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM deleted_features WHERE id=?', (identifier,)).fetchone():
                raise Gone('This feature was deleted. Add it again as a new entry.')
            row = db.execute('SELECT * FROM features WHERE id=?', (identifier,)).fetchone()
            if row:
                # A replayed creation returns the stored entry; later edits use PATCH.
                return self.item(row), False
            now = self.clock()
            db.execute('INSERT INTO features VALUES(?,?,?,?,NULL,?,?)', (identifier, title, detail, body.get('area', 'assistant'), now, now))
            self.bump(db)
            return self.item(db.execute('SELECT * FROM features WHERE id=?', (identifier,)).fetchone()), True

    def update(self, identifier, changes):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM features WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise KeyError(identifier)
            value = dict(row)
            if changes.get('title') is not None: value['title'] = clean_title(changes['title'])
            if changes.get('detail') is not None: value['detail'] = changes['detail'].strip()
            if changes.get('area') is not None: value['area'] = changes['area']
            # Repeating done=true keeps the original completion time, so retries are harmless.
            if changes.get('done') is True and value['done_at'] is None: value['done_at'] = self.clock()
            if changes.get('done') is False: value['done_at'] = None
            if value != dict(row):
                value['updated'] = self.clock()
                db.execute('UPDATE features SET title=?,detail=?,area=?,done_at=?,updated=? WHERE id=?',
                           (value['title'], value['detail'], value['area'], value['done_at'], value['updated'], identifier))
                self.bump(db)
            return self.item(db.execute('SELECT * FROM features WHERE id=?', (identifier,)).fetchone())

    def delete(self, identifier):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('DELETE FROM features WHERE id=?', (identifier,)).rowcount:
                self.bump(db)
            db.execute('INSERT OR IGNORE INTO deleted_features VALUES(?,?)', (identifier, self.clock()))
            return {'deleted': True}


def device_auth(devices):
    def device(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith('Bearer pa_mobile_'):
            raise HTTPException(401, 'Pair the companion app.')
        try:
            return devices.authenticate(authorization[7:])
        except ValueError as error:
            raise HTTPException(401, str(error)) from None
    return device


def features_router(store, auth, prefix):
    """Mount GET/POST <prefix> and PATCH/DELETE <prefix>/{id}.

    POST <prefix>/{id} and POST <prefix>/{id}/delete are equivalents for clients
    whose HTTP stack has no PATCH (Android HttpURLConnection) or prefers POST.
    """
    api = APIRouter(prefix=prefix, dependencies=[Depends(auth)])
    private = {'Cache-Control': 'private, no-store'}

    def known(identifier):
        if not re.fullmatch(ID, identifier):
            raise HTTPException(404, 'Feature not found.')
        return identifier

    @api.get('')
    def snapshot():
        return JSONResponse(store.snapshot(), headers=private)

    @api.post('')
    def create(body: NewFeature, response: Response):
        try:
            item, created = store.create(body.model_dump(exclude_none=True))
        except Gone as error:
            raise HTTPException(409, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        response.status_code = 201 if created else 200
        response.headers.update(private)
        return item

    def edit(identifier: str, body: FeatureEdit):
        try:
            return store.update(known(identifier), body.model_dump(exclude_none=True))
        except KeyError:
            raise HTTPException(404, 'Feature not found.') from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    def remove(identifier: str):
        return store.delete(known(identifier))

    api.add_api_route('/{identifier}', edit, methods=['PATCH', 'POST'])
    api.add_api_route('/{identifier}', remove, methods=['DELETE'])
    api.add_api_route('/{identifier}/delete', remove, methods=['POST'])
    return api
