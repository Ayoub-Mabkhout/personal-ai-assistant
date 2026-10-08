"""Validated APK publication and durable push hints through HA Companion."""
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from contextlib import contextmanager


class ReleaseFeed:
    def __init__(self, apk, clock=time.time):
        self.apk = Path(apk)
        self.path = self.apk.with_name('companion-releases.sqlite3')
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS publication (
                version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL,
                lease REAL NOT NULL DEFAULT 0, accepted REAL)''')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def manifest(self):
        metadata = self.apk.with_suffix('.release.json')
        if not self.apk.is_file() or not metadata.is_file():
            raise FileNotFoundError('Companion release not available.')
        try:
            data = json.loads(metadata.read_text())
            valid = (isinstance(data,dict) and not data.get('diagnostic_only') and data.get('package_name') == 'com.personalassistant.companion'
                     and type(data.get('version_code')) is int and data['version_code'] > 0
                     and isinstance(data.get('version_name'), str) and 0 < len(data['version_name']) < 100
                     and type(data.get('min_sdk')) is int and data['min_sdk'] >= 26
                     and type(data.get('size')) is int and 0 < data['size'] <= 64 * 1024 * 1024
                     and data['size'] == self.apk.stat().st_size
                     and data.get('sha256') == hashlib.sha256(self.apk.read_bytes()).hexdigest())
        except (ValueError, TypeError, OSError):
            raise ValueError('Companion release is being published. Try again shortly.') from None
        if not valid:
            raise ValueError('Companion release is being published. Try again shortly.')
        return data

    def publish(self, version, sha256):
        release = self.manifest()
        if version != release['version_code'] or sha256 != release['sha256']:
            raise ValueError('Publication does not match the downloadable APK.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT sha256 FROM publication WHERE version=?', (version,)).fetchone()
            if old and old[0] != sha256:
                raise ValueError('This version was already published with different bytes. Increment the version.')
            if not old:
                maximum = db.execute('SELECT MAX(version) FROM publication').fetchone()[0]
                if maximum is not None and version < maximum:
                    raise ValueError('Cannot publish an older version.')
                db.execute("UPDATE publication SET state='superseded' WHERE version<? AND state!='accepted'", (version,))
                db.execute("INSERT INTO publication(version,sha256,state,due) VALUES(?,?,'pending',?)", (version, sha256, self.clock()))
        return {**self.status(version), 'created': old is None}

    def status(self, version):
        with self.db() as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM publication WHERE version=?', (version,)).fetchone()
            if row is None:
                return {'version_code': version, 'state': 'unpublished', 'push_api_accepted': False}
            return {'version_code': row['version'], 'state': row['state'],
                    'push_api_accepted': row['state'] == 'accepted', 'attempts': row['attempts']}

    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT version,sha256 FROM publication WHERE state='pending' AND due<=? AND lease<=? ORDER BY version DESC LIMIT 1", (self.clock(), self.clock())).fetchone()
            if row:
                db.execute('UPDATE publication SET lease=?,attempts=attempts+1 WHERE version=?', (self.clock() + 60, row[0]))
                return row

    def outcome(self, version, accepted):
        with self.db() as db:
            if accepted:
                db.execute("UPDATE publication SET state='accepted',accepted=?,lease=0 WHERE version=? AND state='pending'", (self.clock(), version))
            else:
                row = db.execute('SELECT attempts FROM publication WHERE version=?', (version,)).fetchone()
                delay = min(3600, 5 * 2 ** min(row[0], 10))
                db.execute('UPDATE publication SET due=?,lease=0 WHERE version=?', (self.clock() + delay, version))


class CompanionReleasePump:
    """Server-side retries; the phone opens no permanent update connection."""
    def __init__(self, feed, sender, interval=5):
        self.feed, self.sender, self.interval = feed, sender, interval
        self.stop = threading.Event()
        self.thread = None

    def tick(self):
        row = self.feed.claim()
        if not row:
            return
        version, sha256 = row
        try:
            release = self.feed.manifest()
            if release['version_code'] != version or release['sha256'] != sha256:
                self.feed.outcome(version, False)
                return
            self.sender({'message': 'command_broadcast_intent', 'data': {
                'intent_package_name': 'com.personalassistant.companion',
                'intent_class_name': 'com.personalassistant.companion.UpdateReceiver',
                'intent_action': 'com.personalassistant.companion.RELEASE_PUBLISHED',
                'version_code': version, 'sha256': sha256,
                'priority': 'high', 'ttl': 86400}})
        except Exception as error:
            self.feed.outcome(version, False)
            logging.warning('Companion release push failed (%s); retry saved.', type(error).__name__)
        else:
            self.feed.outcome(version, True)

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as error:
                logging.warning('Companion release delivery failed (%s).', type(error).__name__)
            self.stop.wait(self.interval)

    def start(self):
        self.thread = threading.Thread(target=self.run, name='companion-releases', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=12)
