"""Recoverable single-worker execution. Only read-only calendar queries are enabled."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import logging.handlers
import os
from pathlib import Path
import random
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo


class TransportError(Exception):
    def __init__(self, status=None):
        self.status = status
        super().__init__('Relay unavailable' if status is None else f'Relay HTTP {status}')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise TransportError(302)


class RelayClient:
    def __init__(self, base, token_file, timeout=8):
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Relay must use an HTTPS origin and optional /relay path.')
        if parsed.path.rstrip('/') not in ('', '/relay'):
            raise ValueError('Unexpected relay path.')
        self.base, self.token_file, self.timeout = base.rstrip('/'), Path(token_file), timeout
        self.opener = urllib.request.build_opener(NoRedirect)

    def call(self, path, payload=None, method=None):
        token = self.token_file.read_text().strip()
        request = urllib.request.Request(self.base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise TransportError(exc.code) from None
        except (OSError, TimeoutError, ValueError):
            raise TransportError() from None


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                    state TEXT NOT NULL, outcome TEXT, started REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL, at REAL NOT NULL,
                    kind TEXT NOT NULL, detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY, lease TEXT NOT NULL, outcome TEXT NOT NULL,
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    notified INTEGER NOT NULL DEFAULT 0
                );
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(outbox)')}
            for name, definition in [('notification_attempts', 'INTEGER NOT NULL DEFAULT 0'),
                                     ('notify_after', 'REAL NOT NULL DEFAULT 0')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE outbox ADD COLUMN {name} {definition}')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, job_id, kind, detail=None):
        with self.db() as db:
            db.execute('INSERT INTO audit(job_id,at,kind,detail) VALUES(?,?,?,?)',
                (job_id, time.time(), kind, json.dumps(detail or {})))

    def begin(self, job):
        payload = json.dumps(job['payload'], sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        with self.db() as db:
            existing = db.execute('SELECT * FROM runs WHERE id=?', (job['id'],)).fetchone()
            if existing and existing['fingerprint'] != fingerprint:
                raise ValueError('Request ID has different content in local execution records.')
            if existing and existing['outcome']:
                return json.loads(existing['outcome'])
            db.execute('INSERT OR IGNORE INTO runs VALUES(?,?,?,?,?,?,?)',
                (job['id'], fingerprint, payload, 'started', None, time.time(), time.time()))
        self.event(job['id'], 'started', {'attempt': job['attempts']})
        return None

    def outcome(self, job_id, outcome):
        with self.db() as db:
            db.execute("UPDATE runs SET state='outcome_ready',outcome=?,updated=? WHERE id=?",
                (json.dumps(outcome, ensure_ascii=False), time.time(), job_id))
        self.event(job_id, 'outcome_saved', {'state': outcome['state']})

    def acknowledged(self, job_id):
        with self.db() as db:
            db.execute("UPDATE runs SET state='acknowledged',updated=? WHERE id=?", (time.time(), job_id))
            db.execute('UPDATE outbox SET acknowledged=1 WHERE id=?', (job_id,))
        self.event(job_id, 'relay_acknowledged')

    def enqueue_ack(self, job, outcome):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO outbox(id,lease,outcome) VALUES(?,?,?)',
                (job['id'], job['lease_token'], json.dumps(outcome, ensure_ascii=False)))

    def pending(self):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM outbox WHERE acknowledged=0 OR notified=0')]

    def notified(self, job_id):
        with self.db() as db:
            db.execute('UPDATE outbox SET notified=1 WHERE id=?', (job_id,))

    def notification_failed(self, job_id, attempts):
        delay = min(3600, 30 * 2 ** min(attempts, 7))
        with self.db() as db:
            db.execute('UPDATE outbox SET notification_attempts=?,notify_after=? WHERE id=?',
                (attempts + 1, time.time() + delay, job_id))

    def obsolete(self, job_id):
        with self.db() as db:
            db.execute('DELETE FROM outbox WHERE id=?', (job_id,))
        self.event(job_id, 'acknowledgement_lease_rejected')


def calendar_range(payload):
    """Use the original request date, even if execution happens after midnight."""
    text = re.sub(r'[?!.,]', '', payload['command'].casefold()).strip()
    text = re.sub(r'^(to|please)\s+', '', text)
    if not any(word in text for word in ('calendar', 'agenda', 'schedule', 'appointments')):
        return None
    if re.search(r'\b(add|create|cancel|delete|move|reschedule|book|remind)\b', text):
        return None
    tz = ZoneInfo(payload['timezone'])
    original = datetime.fromisoformat(payload['created_at'])
    if original.tzinfo is None:
        raise ValueError('Request timestamp must include its UTC offset.')
    today = original.astimezone(tz).date()
    duration = 1
    if 'day after tomorrow' in text:
        start = today + timedelta(days=2)
    elif 'tomorrow' in text:
        start = today + timedelta(days=1)
    elif 'next week' in text:
        start = today + timedelta(days=7-today.weekday())
        duration = 7
    elif 'this week' in text:
        start = today - timedelta(days=today.weekday())
        duration = 7
    elif match := re.search(r'\b(\d{4}-\d{2}-\d{2})\b', text):
        start = datetime.strptime(match[1], '%Y-%m-%d').date()
    elif any(day in text for day in ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')):
        return None  # "next Friday" needs an explicit interpretation, not a silent guess.
    else:
        start = today
    return start.isoformat(), (start + timedelta(days=duration)).isoformat()


class CalendarExecutor:
    def __init__(self, config):
        self.config = config

    def available(self):
        return Path(self.config['calendar_db']).is_file() and Path(self.config['python']).is_file()

    def execute(self, job, cancelled):
        payload = dict(job['payload'])
        payload['created_at'] = payload.get('created_at') or datetime.fromtimestamp(job['created'], timezone.utc).isoformat()
        window = calendar_range(payload)
        if not window:
            return {'state': 'needs_input', 'result': {'summary':
                'The laptop is connected. This first worker supports calendar queries for today, tomorrow, this week, next week or an ISO date. Other task types are not enabled yet.'}}
        if cancelled.is_set():
            raise InterruptedError('Execution lease was lost.')
        bounds = [datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(payload['timezone'])).isoformat()
            for value in window]
        args = [self.config['python'], str(Path(self.config['repository']) / 'assistant_calendar.py'),
            '--db', self.config['calendar_db'], 'agenda', '--from', bounds[0], '--to', bounds[1]]
        process = subprocess.run(args, capture_output=True, timeout=20, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if process.returncode:
            return {'state': 'failed', 'result': {'summary': 'The local calendar could not be read. Check the worker log.'}}
        entries = json.loads(process.stdout)
        summary = f'No appointments from {window[0]} to {window[1]} (end exclusive).' if not entries else '\n'.join(
            f"{x['start_date'] if x['all_day'] else x['start']}: {x['title']}" for x in entries)
        return {'state': 'completed', 'result': {'summary': summary, 'events': entries,
            'range': {'from': window[0], 'to_exclusive': window[1], 'timezone': payload['timezone']},
            'original_request_time': payload['created_at'], 'verified_at': datetime.now(timezone.utc).isoformat(),
            'executor': 'calendar.agenda'}}


class LeaseKeeper:
    def __init__(self, client, job, shutdown, interval=15, lease_seconds=120):
        self.client, self.job, self.shutdown = client, job, shutdown
        self.interval, self.lease_seconds = interval, lease_seconds
        self.cancelled, self.done = threading.Event(), threading.Event()
        self.deadline = time.monotonic() + lease_seconds - 10

    def __enter__(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self.cancelled

    def run(self):
        while not self.done.wait(self.interval):
            if self.shutdown.is_set() or time.monotonic() >= self.deadline:
                self.cancelled.set()
                return
            try:
                self.client.call('/v1/worker/' + self.job['id'] + '/renew',
                    {'lease_token': self.job['lease_token'], 'lease_seconds': self.lease_seconds})
                self.deadline = time.monotonic() + self.lease_seconds - 10
                self.client.call('/v1/worker/heartbeat', {'readiness': 'ready'})
            except TransportError as exc:
                if exc.status in (401, 403, 404, 409, 422):
                    self.cancelled.set()
                    return

    def __exit__(self, *args):
        self.done.set()
        self.thread.join(timeout=20)


class Singleton:
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.handle = self.path.open('a+b')
        if self.handle.tell() == 0:
            self.handle.write(b'1')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError('Another laptop worker is already running.') from None
        return self

    def __exit__(self, *args):
        self.handle.close()


class Worker:
    def __init__(self, config, client=None, executor=None, notifier=None):
        self.config = config
        self.directory = Path(config['runtime_dir'])
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.directory / 'execution.sqlite3')
        self.client = client or RelayClient(config['relay_url'], config['worker_token_file'])
        self.executor = executor or CalendarExecutor(config)
        self.notifier = notifier
        self.shutdown = threading.Event()

    def status(self, state, **extra):
        record = {'state': state, 'pid': os.getpid(), 'updated_at': datetime.now(timezone.utc).isoformat(),
            'capabilities': getattr(self.executor,'capabilities',['calendar.agenda']), **extra}
        temp = self.directory / 'status.new'
        temp.write_text(json.dumps(record), encoding='utf-8')
        temp.replace(self.directory / 'status.json')

    def tick(self):
        if (self.directory / 'pause.flag').exists() or Path(self.config.get('pause_file',self.directory / 'pause.flag')).exists():
            self.client.call('/v1/worker/heartbeat', {'readiness': 'blocked'})
            self.status('paused')
            return False
        if not self.executor.available():
            self.client.call('/v1/worker/heartbeat', {'readiness': 'blocked'})
            self.status('blocked', reason='calendar_or_runtime_missing')
            return False
        self.client.call('/v1/worker/heartbeat', {'readiness': 'ready'})
        self.status('ready')
        self.flush_outbox()
        job = self.client.call('/v1/worker/claim', {'lease_seconds': 120})['job']
        if job is None:
            return False
        self.status('running', job_id=job['id'])
        with LeaseKeeper(self.client, job, self.shutdown) as cancelled:
            outcome = self.ledger.begin(job)
            if outcome is None:
                outcome = self.executor.execute(job, cancelled)
                self.ledger.outcome(job['id'], outcome)
            if cancelled.is_set() or self.shutdown.is_set():
                self.ledger.event(job['id'], 'lease_lost_before_acknowledgement')
                return True
            self.ledger.enqueue_ack(job, outcome)
            self.flush_outbox()
        self.status('ready')
        return True

    def flush_outbox(self):
        for row in self.ledger.pending():
            outcome = json.loads(row['outcome'])
            if not row['acknowledged']:
                try:
                    self.client.call('/v1/worker/' + row['id'] + '/result',
                        {'lease_token': row['lease'], **outcome})
                    self.ledger.acknowledged(row['id'])
                except TransportError as exc:
                    if exc.status in (404,409,422):
                        self.ledger.obsolete(row['id'])
                        continue
                    raise
            if self.notifier:
                if row['notify_after'] > time.time():
                    continue
                try:
                    self.notifier(row['id'], outcome)
                    self.ledger.event(row['id'], 'notification_accepted')
                except Exception as exc:
                    self.ledger.event(row['id'], 'notification_failed', {'type': type(exc).__name__})
                    self.ledger.notification_failed(row['id'], row['notification_attempts'])
                    continue
            self.ledger.notified(row['id'])

    def run(self):
        delay = 2
        with Singleton(self.directory / 'worker.lock'):
            self.status('starting')
            while not self.shutdown.is_set():
                try:
                    self.tick()
                    delay = 2
                    self.shutdown.wait(self.config.get('poll_seconds', 4))
                except TransportError as exc:
                    self.status('authentication_blocked' if exc.status in (401,403) else 'disconnected', http_status=exc.status)
                    logging.warning('Worker relay connection: %s', exc)
                    self.shutdown.wait(delay + random.uniform(0, min(2, delay/4)))
                    delay = min(60, delay * 2)
                except Exception as exc:
                    self.status('blocked', reason=type(exc).__name__)
                    logging.error('Worker operation failed: %s', type(exc).__name__)
                    try:
                        self.client.call('/v1/worker/heartbeat', {'readiness': 'blocked'})
                    except (TransportError, OSError):
                        pass
                    self.shutdown.wait(15)
            self.status('stopped')


def main():
    import argparse
    import signal
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    directory = Path(config['runtime_dir'])
    directory.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(directory / 'worker.log', maxBytes=262144, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    worker = Worker(config)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: worker.shutdown.set())
    if args.once:
        with Singleton(directory / 'worker.lock'):
            worker.tick()
    else:
        worker.run()


if __name__ == '__main__':
    main()
