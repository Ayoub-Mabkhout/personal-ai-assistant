"""SQLite command queue with transactional claims and fenced worker leases."""

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .wakeups import Wakeups, log_phases

CLAIMABLE = 'claimable'


class Conflict(ValueError):
    pass


class Missing(ValueError):
    pass


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Timestamps must include an explicit UTC offset.')
    return parsed.timestamp()


class Queue:
    def __init__(self, path, clock=time.time, serial=False, notifications=False, server_enabled=False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.serial = serial
        self.server_enabled = server_enabled
        self.notifications_enabled = notifications
        self.wakeups = Wakeups()
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, source TEXT NOT NULL,
                    created REAL NOT NULL, expires REAL, state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT,
                    lease_until REAL, result TEXT, updated REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_state_created ON jobs(state, created);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    at REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worker (
                    id INTEGER PRIMARY KEY CHECK(id=1), seen REAL NOT NULL,
                    readiness TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS server_worker (
                    id INTEGER PRIMARY KEY CHECK(id=1), seen REAL NOT NULL,
                    readiness TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    job_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    delivered_revision INTEGER NOT NULL DEFAULT 0,
                    fingerprint TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT
                );
            ''')

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def audit(self, db, job_id, kind, data=None):
        event=db.execute('INSERT INTO events(job_id,at,kind,data) VALUES(?,?,?,?)',
                   (job_id, self.clock(), kind, json.dumps(data or {})))
        if self.notifications_enabled and kind in ('submitted','claimed','lease_expired','completed','failed','needs_input','cancelled','expired','notification_requested'):
            db.execute('''INSERT INTO notification_outbox(job_id,revision) VALUES(?,?)
                ON CONFLICT(job_id) DO UPDATE SET revision=excluded.revision,
                attempts=0,next_attempt=0,last_error=NULL''',(job_id,event.lastrowid))

    def notification_rows(self):
        with self.connection(True) as db:
            self.maintenance(db)
            return [dict(row) for row in db.execute('''SELECT n.*,j.state,e.at AS changed,e.kind AS cause FROM notification_outbox n
                JOIN jobs j ON j.id=n.job_id LEFT JOIN events e ON e.seq=n.revision WHERE n.revision!=n.delivered_revision
                OR j.state IN ('queued','running') ORDER BY n.revision''')]

    def notify_again(self,request_id):
        if not self.notifications_enabled: raise ValueError('Phone notifications are disabled.')
        with self.connection(True) as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(request_id,)).fetchone()
            record=self.record(row)
            self.audit(db,request_id,'notification_requested')
            return record

    def notification_accepted(self,job_id,revision,fingerprint):
        with self.connection(True) as db:
            updated=db.execute('''UPDATE notification_outbox SET delivered_revision=?,fingerprint=?,
                attempts=0,next_attempt=0,last_error=NULL WHERE job_id=? AND revision=?''',
                (revision,fingerprint,job_id,revision)).rowcount
            if updated:
                db.execute('INSERT INTO events(job_id,at,kind,data) VALUES(?,?,?,?)',
                    (job_id,self.clock(),'phone_notification_accepted',json.dumps({'revision':revision})))

    def notification_expired(self,job_id,revision):
        with self.connection(True) as db:
            db.execute('''UPDATE notification_outbox SET delivered_revision=?,fingerprint=NULL,attempts=0,next_attempt=0,
                last_error=NULL WHERE job_id=? AND revision=?''',(revision,job_id,revision))

    def notification_failed(self,job_id,revision,error):
        with self.connection(True) as db:
            row=db.execute('SELECT attempts FROM notification_outbox WHERE job_id=? AND revision=?',(job_id,revision)).fetchone()
            if row:
                delay=min(300,5*2**min(row['attempts'],6))
                db.execute('''UPDATE notification_outbox SET attempts=attempts+1,next_attempt=?,last_error=?
                    WHERE job_id=? AND revision=?''',(self.clock()+delay,error,job_id,revision))

    def maintenance(self, db):
        now = self.clock()
        for row in db.execute("SELECT id FROM jobs WHERE state IN ('queued','running') AND expires<=?", (now,)).fetchall():
            db.execute("UPDATE jobs SET state='expired',lease_token=NULL,lease_until=NULL,updated=? WHERE id=?", (now, row['id']))
            self.audit(db, row['id'], 'expired')
        for row in db.execute("SELECT id FROM jobs WHERE state='running' AND lease_until<=?", (now,)).fetchall():
            db.execute("UPDATE jobs SET state='queued',lease_token=NULL,lease_until=NULL,updated=? WHERE id=?", (now, row['id']))
            self.audit(db, row['id'], 'lease_expired')

    @staticmethod
    def record(row, include_lease=False):
        if row is None:
            raise Missing('Command not found.')
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        result['result'] = json.loads(result['result']) if result['result'] else None
        if not include_lease:
            result.pop('lease_token')
        return result

    def submit(self, payload, source='owner_api'):
        request_id = payload['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', request_id):
            raise ValueError('Command ID must contain 8-64 letters, numbers, underscores or hyphens.')
        if not isinstance(payload['command'], str) or not payload['command'].strip() or len(payload['command']) > 4096:
            raise ValueError('Command must contain 1-4096 characters.')
        try:
            ZoneInfo(payload['timezone'])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Unknown timezone.') from exc
        if self.server_enabled and self.server_request(payload['command']) and not self.session_root(payload):
            payload = {**payload, 'execution_host': 'server'}
        created = timestamp(payload['created_at']) if payload.get('created_at') else self.clock()
        expires = timestamp(payload['expires_at']) if payload.get('expires_at') else None
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        with self.connection(True) as db:
            self.maintenance(db)
            existing = db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone()
            if existing:
                if existing['payload'] != encoded or existing['source'] != source:
                    raise Conflict('This command ID already has different content.')
                return self.record(existing), False
            if created > self.clock() + 300:
                raise ValueError('Creation time is too far in the future.')
            if expires is not None and expires <= created:
                raise ValueError('Expiry must follow creation time.')
            state = 'expired' if expires is not None and expires <= self.clock() else 'queued'
            db.execute('INSERT INTO jobs(id,payload,source,created,expires,state,updated) VALUES(?,?,?,?,?,?,?)',
                       (request_id, encoded, source, created, expires, state, self.clock()))
            self.audit(db, request_id, 'submitted', {'state': state})
            record = self.record(db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone())
        if state == 'queued':
            self.wakeups.notify(CLAIMABLE)
        return record, True

    def get(self, request_id):
        with self.connection(True) as db:
            self.maintenance(db)
            return self.record(db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone())

    def history(self, request_id):
        self.get(request_id)
        with self.connection() as db:
            return [{**dict(r), 'data': json.loads(r['data'])} for r in
                    db.execute('SELECT * FROM events WHERE job_id=? ORDER BY seq', (request_id,))]

    def heartbeat(self, readiness, execution_host='laptop'):
        if readiness not in ('ready', 'blocked'):
            raise ValueError('Readiness must be ready or blocked.')
        with self.connection(True) as db:
            table = 'server_worker' if execution_host == 'server' else 'worker'
            db.execute(f'INSERT INTO {table}(id,seen,readiness) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET seen=excluded.seen,readiness=excluded.readiness',
                       (self.clock(), readiness))
        return self.status()

    def status(self):
        with self.connection(True) as db:
            self.maintenance(db)
            row = db.execute('SELECT * FROM worker WHERE id=1').fetchone()
            state = row['readiness'] if row and self.clock() - row['seen'] < 60 else 'unavailable'
            queued = db.execute("SELECT COUNT(*) FROM jobs WHERE state='queued'").fetchone()[0]
            result = {'laptop': state, 'last_seen': row['seen'] if row else None, 'queued': queued}
            if self.server_enabled:
                server = db.execute('SELECT * FROM server_worker WHERE id=1').fetchone()
                result['server'] = server['readiness'] if server and self.clock() - server['seen'] < 60 else 'unavailable'
            return result

    @staticmethod
    def server_request(command):
        return bool(re.match(r'^\s*server:\s*\S', command, re.IGNORECASE))

    def execution_host(self, db, payload):
        root = self.session_root(payload)
        if root:
            row = db.execute('SELECT payload FROM jobs WHERE id=?', (root,)).fetchone()
            payload = json.loads(row['payload']) if row else {}
        return 'server' if payload.get('execution_host') == 'server' else 'laptop'

    @staticmethod
    def session_root(payload):
        continuation = payload.get('resume_task')
        if isinstance(continuation, dict):
            root = continuation.get('root_id')
            if isinstance(root, str) and re.fullmatch(r'[A-Za-z0-9_-]{8,64}', root):
                return root
        return None

    def execution_lane(self, db, row):
        """Explicit contexts use their actual last worker session when it is known."""
        payload = json.loads(row['payload'])
        root = self.session_root(payload)
        if not root:
            return 'general:' + self.execution_host(db, payload)
        # Older intelligent routing could make two roots share the same CLI session.
        # Include completed follow-ups because an allowance fallback can move a context.
        results = db.execute('''SELECT result FROM jobs WHERE result IS NOT NULL AND
            (id=? OR json_extract(payload,'$.resume_task.root_id')=?) ORDER BY rowid DESC''', (root,root))
        for latest in results:
            result = json.loads(latest['result'])
            workers = result.get('workers') or []
            worker = workers[-1] if workers and isinstance(workers[-1], dict) else {}
            session = worker.get('session_id') or result.get('resumed_session_id') or result.get('orchestrator_session_id')
            if isinstance(session, str) and session:
                agent = worker.get('agent') or result.get('orchestrator_agent') or 'codex'
                return 'session:'+agent+':'+session
        return 'task:'+root

    def lane_candidate(self, db, execution_host='laptop'):
        running = db.execute("SELECT * FROM jobs WHERE state='running'").fetchall()
        occupied = {self.execution_lane(db, row) for row in running}
        active_roots = {self.session_root(json.loads(row['payload'])) or row['id'] for row in running}
        for row in db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY rowid").fetchall():
            payload = json.loads(row['payload'])
            if self.execution_host(db, payload) != execution_host:
                continue
            root = self.session_root(payload)
            if root:
                original = db.execute('SELECT state FROM jobs WHERE id=?', (root,)).fetchone()
                if root in active_roots or (original and original['state'] in ('queued','running')):
                    continue
            if self.execution_lane(db, row) not in occupied:
                return row
        return None

    def claim(self, lease_seconds=60, session_lanes=False, execution_host='laptop'):
        self.validate_duration(lease_seconds)
        with self.connection(True) as db:
            self.maintenance(db)
            table = 'server_worker' if execution_host == 'server' else 'worker'
            worker = db.execute(f'SELECT * FROM {table} WHERE id=1').fetchone()
            if not worker or worker['readiness'] != 'ready' or self.clock() - worker['seen'] >= 60:
                return None
            if self.serial and not session_lanes and db.execute("SELECT 1 FROM jobs WHERE state='running' LIMIT 1").fetchone():
                return None
            order = 'rowid' if self.serial else 'created,id'
            if self.serial and session_lanes:
                row = self.lane_candidate(db, execution_host)
            elif self.serial:
                candidates = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY " + order)
                row = next((item for item in candidates
                            if self.execution_host(db, json.loads(item['payload'])) == execution_host), None)
            else:
                row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY " + order + " LIMIT 1").fetchone()
            if row is None:
                return None
            token = str(uuid4())
            db.execute("UPDATE jobs SET state='running',attempts=attempts+1,lease_token=?,lease_until=?,updated=? WHERE id=?",
                       (token, self.clock() + lease_seconds, self.clock(), row['id']))
            self.audit(db, row['id'], 'claimed', {'attempt': row['attempts'] + 1})
            return self.record(db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone(), True)

    @staticmethod
    def validate_duration(seconds):
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 15 <= seconds <= 300:
            raise ValueError('Lease duration must be 15-300 seconds.')

    def owned(self, db, request_id, token):
        row = db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone()
        if row is None:
            raise Missing('Command not found.')
        if row['state'] != 'running' or row['lease_token'] != token or row['lease_until'] <= self.clock():
            raise Conflict('Worker lease is no longer current.')
        return row

    def renew(self, request_id, token, lease_seconds=60):
        self.validate_duration(lease_seconds)
        with self.connection(True) as db:
            self.maintenance(db)
            self.owned(db, request_id, token)
            db.execute('UPDATE jobs SET lease_until=?,updated=? WHERE id=?',
                       (self.clock() + lease_seconds, self.clock(), request_id))
            return self.record(db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone(), True)

    def finish(self, request_id, token, state, result, timings=None):
        if state not in ('completed', 'failed', 'needs_input'):
            raise ValueError('Invalid result state.')
        record = self._finish(request_id, token, state, result, timings)
        if self.serial:  # the next queued job became claimable
            self.wakeups.notify(CLAIMABLE)
        return record

    def _finish(self, request_id, token, state, result, timings):
        with self.connection(True) as db:
            self.maintenance(db)
            # Allow an identical acknowledgement retry after a lost HTTP response.
            row = db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone()
            encoded = json.dumps(result, sort_keys=True, ensure_ascii=False)
            if row and row['state'] == state and row['lease_token'] == token and row['result'] == encoded:
                return self.record(row)
            self.owned(db, request_id, token)
            db.execute('UPDATE jobs SET state=?,result=?,lease_until=NULL,updated=? WHERE id=?',
                       (state, encoded, self.clock(), request_id))
            if timings:
                self.audit(db, request_id, 'worker_timings', timings)
            self.audit(db, request_id, state)
            record = self.record(db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone())
            self.log_phases(db, row, state, timings or {})
            return record

    def log_phases(self, db, row, state, timings):
        """queued -> claimed -> execution started -> first output -> finished, from the audit trail."""
        claims = [r['at'] for r in db.execute("SELECT at FROM events WHERE job_id=? AND kind='claimed' ORDER BY seq", (row['id'],))]
        if not claims:
            return
        claimed, now = claims[-1], self.clock()
        started = timings.get('execution_started_after')
        executed = timings.get('execution_finished_after')
        log_phases('agent' if self.serial else 'command',
                   f"source={row['source']} state={state} attempts={len(claims)}", [
            ('queued_to_claimed', claims[0] - row['created']),
            ('claimed_to_started', started),
            ('started_to_first_output', timings.get('first_output_after') - started
             if timings.get('first_output_after') is not None and started is not None else None),
            ('execution', executed - started if executed is not None and started is not None else None),
            ('claimed_to_finished', now - claimed),
            ('total', now - row['created'])])

    def cancel(self, request_id):
        with self.connection(True) as db:
            self.maintenance(db)
            row = db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone()
            if row is None:
                raise Missing('Command not found.')
            if row['state'] in ('queued', 'running'):
                db.execute("UPDATE jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,updated=? WHERE id=?", (self.clock(), request_id))
                self.audit(db, request_id, 'cancelled')
            record = self.record(db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone())
        if self.serial:
            self.wakeups.notify(CLAIMABLE)
        return record
