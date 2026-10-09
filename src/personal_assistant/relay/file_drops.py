"""Owner-requested files delivered to the paired Companion phone.

The laptop worker (or the owner submit credential) uploads one file under a stable ID.
The relay keeps it under its data directory with its SHA-256, journals a native ``file``
event for the phone and deletes the bytes once the phone confirms a verified download,
or when the drop expires. Retries of the same ID never create a second file or event.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

ID = r'^[A-Za-z0-9_-]{8,64}$'
MIB = 1024 * 1024
MIME = re.compile(r'[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}')
FIELDS = {'name', 'size', 'sha256', 'mime', 'note', 'phone'}
FINAL_RETENTION = 30 * 86400
ORPHAN_AGE = 3600


class Receipt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


def clean_name(value):
    """A display file name only: no directories, control characters or dot-only names."""
    if not isinstance(value, str):
        raise ValueError('File name required.')
    name = ' '.join(value.split())
    if (not name or len(name) > 150 or name.strip('.') == '' or any(c in name for c in '/\\:*?"<>|')
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Use a plain file name without folders or special characters.')
    return name


def manifest(encoded, max_bytes):
    try:
        if not encoded or len(encoded) > 8192:
            raise ValueError()
        value = json.loads(base64.b64decode(encoded, validate=True).decode('utf-8'))
        if not isinstance(value, dict) or set(value) - FIELDS:
            raise ValueError()
        size, digest = value.get('size'), value.get('sha256')
        if type(size) is not int or not 0 <= size:
            raise ValueError()
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError()
        mime = value.get('mime') or 'application/octet-stream'
        note = value.get('note') or ''
        phone = value.get('phone')
        if not isinstance(mime, str) or not MIME.fullmatch(mime.lower()):
            raise ValueError()
        if not isinstance(note, str) or len(note) > 300 or any(ord(c) < 32 and c != '\n' for c in note):
            raise ValueError()
        if phone is not None and (not isinstance(phone, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', phone)):
            raise ValueError()
        result = {'name': clean_name(value.get('name')), 'size': size, 'sha256': digest,
                  'mime': mime.lower(), 'note': note.strip(), 'phone': phone}
    except (TypeError, ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'Invalid file manifest.') from None
    if size > max_bytes:
        raise HTTPException(413, 'File exceeds the %d MiB phone transfer limit.' % (max_bytes // MIB))
    return result


class FileDrops:
    def __init__(self, events, directory, max_bytes=50 * MIB, ttl=7 * 86400, quota=1024 * MIB):
        self.events, self.devices = events, events.devices
        self.clock = self.devices.clock
        self.max_bytes, self.ttl, self.quota = int(max_bytes), int(ttl), int(quota)
        if self.max_bytes < 1 or self.ttl < 3600 or self.quota < self.max_bytes:
            raise ValueError('Invalid file transfer limits.')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass
        self.lock = threading.Lock()
        with self.devices.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS file_drops(
                id TEXT PRIMARY KEY,phone TEXT NOT NULL,name TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,note TEXT NOT NULL,requested_phone TEXT,created REAL NOT NULL,expires REAL NOT NULL,
                state TEXT NOT NULL,finished REAL);
                CREATE INDEX IF NOT EXISTS file_drops_phone ON file_drops(phone,state);''')

    def blob(self, identifier):
        if not re.fullmatch(ID, identifier):
            raise HTTPException(404, 'File not found.')
        return self.directory / identifier

    @staticmethod
    def public(row):
        keys = ('id', 'phone', 'name', 'mime', 'size', 'sha256', 'note', 'created', 'expires', 'state', 'finished')
        return {key: row[key] for key in keys}

    def sweep(self):
        """Expire drops past their TTL or for revoked phones; delete their bytes and stale records."""
        now = self.clock()
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            gone = db.execute('''SELECT id FROM file_drops WHERE state='ready' AND (expires<=? OR phone NOT IN
                (SELECT id FROM phones WHERE revoked=0))''', (now,)).fetchall()
            db.execute('''UPDATE file_drops SET state='expired',finished=? WHERE state='ready' AND (expires<=? OR phone NOT IN
                (SELECT id FROM phones WHERE revoked=0))''', (now, now))
            db.execute("DELETE FROM file_drops WHERE state!='ready' AND finished<=?", (now - FINAL_RETENTION,))
            ready = {row['id'] for row in db.execute("SELECT id FROM file_drops WHERE state='ready'")}
        for row in gone:
            (self.directory / row['id']).unlink(missing_ok=True)
        for path in self.directory.iterdir():
            # Bytes without a ready record: an interrupted upload or a crash between rename and insert.
            try:
                if path.name not in ready and now - path.stat().st_mtime > ORPHAN_AGE:
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    def phones(self):
        with self.devices.db() as db:
            return [dict(row) for row in db.execute('SELECT id,name,created,seen FROM phones WHERE revoked=0 ORDER BY created')]

    def recipient(self, requested):
        active = [phone['id'] for phone in self.phones()]
        if requested:
            if requested not in active:
                raise HTTPException(409, 'That phone is not paired or has been revoked.')
            return requested
        if len(active) == 1:
            return active[0]
        if not active:
            raise HTTPException(409, 'Pair Assistant Companion first; no active phone is paired.')
        raise HTTPException(409, 'More than one phone is paired. Choose one with its phone ID.')

    def room(self, size, db=None):
        if db is None:
            with self.devices.db() as own:
                return self.room(size, own)
        stored = db.execute("SELECT COALESCE(SUM(size),0) FROM file_drops WHERE state='ready'").fetchone()[0]
        if stored + size > self.quota:
            raise HTTPException(507, 'Relay file storage is full; wait for earlier files to be downloaded.')

    def get(self, identifier):
        self.blob(identifier)
        with self.devices.db() as db:
            return db.execute('SELECT * FROM file_drops WHERE id=?', (identifier,)).fetchone()

    @staticmethod
    def same(row, value):
        return all(row[key] == value[key] for key in ('name', 'size', 'sha256', 'mime', 'note')) and \
            (row['requested_phone'] or None) == value['phone']

    def announce(self, row):
        """Journal the phone hint. The payload is stable, so a retried announcement is collapsed."""
        if row['state'] != 'ready':
            return
        body = {'type': 'file', 'tag': 'file-' + row['id'], 'file_id': row['id'], 'title': 'File ready: ' + row['name'],
                'message': row['note'] or row['name'], 'name': row['name'], 'mime': row['mime'], 'size': row['size'],
                'sha256': row['sha256'], 'visibility': 'private'}
        self.events.enqueue(body, ttl=max(60, min(86400, int(row['expires'] - self.clock()))), phone=row['phone'])

    def existing(self, row, value):
        if not self.same(row, value):
            raise HTTPException(409, 'This file ID already holds a different file.')
        self.announce(row)
        return {**self.public(row), 'created_now': False}

    async def upload(self, identifier, value, stream, declared_length=None):
        target = self.blob(identifier)
        self.sweep()
        old = self.get(identifier)
        if old:
            return self.existing(old, value)
        phone = self.recipient(value['phone'])
        if declared_length is not None and declared_length != value['size']:
            raise HTTPException(400, 'Upload length differs from its manifest.')
        self.room(value['size'])
        staged = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix='.upload-', delete=False) as output:
                staged = Path(output.name)
                digest, count = hashlib.sha256(), 0
                async for chunk in stream:
                    count += len(chunk)
                    if count > value['size']:
                        raise HTTPException(413, 'Upload exceeds its declared size.')
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if count != value['size'] or not hmac.compare_digest(digest.hexdigest(), value['sha256']):
                raise HTTPException(400, 'Upload checksum or length mismatch.')
            with self.lock:
                with self.devices.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT * FROM file_drops WHERE id=?', (identifier,)).fetchone()
                    if not row:
                        self.room(value['size'], db)
                        os.replace(staged, target)
                        staged = None
                        now = self.clock()
                        db.execute('''INSERT INTO file_drops(id,phone,name,mime,size,sha256,note,requested_phone,created,expires,state)
                            VALUES(?,?,?,?,?,?,?,?,?,?,'ready')''', (identifier, phone, value['name'], value['mime'], value['size'],
                            value['sha256'], value['note'], value['phone'], now, now + self.ttl))
                        row = db.execute('SELECT * FROM file_drops WHERE id=?', (identifier,)).fetchone()
                        created = True
                    else:
                        created = False
            if not created:
                return self.existing(row, value)
            self.announce(row)
            return {**self.public(row), 'created_now': True}
        finally:
            if staged:
                staged.unlink(missing_ok=True)

    def status(self, identifier):
        self.sweep()
        row = self.get(identifier)
        if not row:
            raise HTTPException(404, 'File not found.')
        return self.public(row)

    def cancel(self, identifier):
        self.sweep()
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM file_drops WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise HTTPException(404, 'File not found.')
            if row['state'] == 'ready':
                db.execute("UPDATE file_drops SET state='cancelled',finished=? WHERE id=?", (self.clock(), identifier))
        self.blob(identifier).unlink(missing_ok=True)
        return self.public(self.get(identifier))

    def pending(self, phone):
        self.sweep()
        with self.devices.db() as db:
            rows = db.execute("SELECT * FROM file_drops WHERE phone=? AND state='ready' ORDER BY created LIMIT 50", (phone,)).fetchall()
        return {'items': [{key: row[key] for key in ('id', 'name', 'mime', 'size', 'sha256', 'note', 'created', 'expires')} for row in rows]}

    def content(self, phone, identifier):
        self.sweep()
        target = self.blob(identifier)
        row = self.get(identifier)
        if not row or row['phone'] != phone:
            raise HTTPException(404, 'File not found.')
        if row['state'] != 'ready' or not target.is_file():
            raise HTTPException(410, 'File is no longer available.')
        return row, target

    def receipt(self, phone, identifier, digest):
        self.blob(identifier)
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM file_drops WHERE id=? AND phone=?', (identifier, phone)).fetchone()
            if not row:
                raise HTTPException(404, 'File not found.')
            if not hmac.compare_digest(row['sha256'], digest):
                raise HTTPException(409, 'Downloaded file checksum differs; download it again.')
            if row['state'] == 'ready':
                db.execute("UPDATE file_drops SET state='delivered',finished=? WHERE id=?", (self.clock(), identifier))
        self.blob(identifier).unlink(missing_ok=True)
        return {'id': identifier, 'state': self.get(identifier)['state']}


def file_drop_router(drops, owner_tokens, device_auth):
    """Owner/worker upload under /v1/files; paired-phone download under /groceries/v1/mobile/files."""
    tokens = [token.encode() for token in owner_tokens]
    owner_api, phone_api = APIRouter(prefix='/v1/files'), APIRouter(prefix='/groceries/v1/mobile/files')

    def owner(authorization: str | None = Header(default=None)):
        given = (authorization or '').encode()
        # Compare against every credential so timing does not reveal which one matched.
        if not any([hmac.compare_digest(given, b'Bearer ' + token) for token in tokens]):
            raise HTTPException(401, 'Authentication required.', headers={'WWW-Authenticate': 'Bearer'})

    @owner_api.get('/phones', dependencies=[Depends(owner)])
    def phones():
        return {'phones': drops.phones(), 'max_bytes': drops.max_bytes, 'ttl': drops.ttl}

    @owner_api.put('/{identifier}', dependencies=[Depends(owner)])
    async def upload(identifier: str, request: Request, x_file_manifest: str = Header(default='')):
        value = manifest(x_file_manifest, drops.max_bytes)
        length = request.headers.get('content-length')
        try:
            length = None if length is None else int(length)
        except ValueError:
            raise HTTPException(400, 'Invalid upload length.') from None
        return await drops.upload(identifier, value, request.stream(), length)

    @owner_api.get('/{identifier}', dependencies=[Depends(owner)])
    def status(identifier: str):
        return drops.status(identifier)

    @owner_api.post('/{identifier}/cancel', dependencies=[Depends(owner)])
    def cancel(identifier: str):
        return drops.cancel(identifier)

    @phone_api.get('')
    def pending(phone=Depends(device_auth)):
        return drops.pending(phone)

    @phone_api.get('/{identifier}')
    def download(identifier: str, phone=Depends(device_auth)):
        row, target = drops.content(phone, identifier)
        return FileResponse(target, media_type='application/octet-stream', headers={
            'X-File-Sha256': row['sha256'], 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Disposition': 'attachment; filename="download"'})

    @phone_api.post('/{identifier}/receipt')
    def receipt(identifier: str, body: Receipt, phone=Depends(device_auth)):
        return drops.receipt(phone, identifier, body.sha256)

    return owner_api, phone_api


def settings_from_environment(environ=os.environ):
    def number(name, default):
        try:
            return float(environ.get(name, default))
        except ValueError:
            raise ValueError(name + ' must be a number.') from None
    return {'max_bytes': int(number('ASSISTANT_FILE_DROP_MAX_MIB', 50) * MIB),
            'ttl': int(number('ASSISTANT_FILE_DROP_TTL_DAYS', 7) * 86400),
            'quota': int(number('ASSISTANT_FILE_DROP_QUOTA_MIB', 1024) * MIB)}
