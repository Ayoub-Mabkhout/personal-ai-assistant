"""Assistant-managed local calendar. All CLI output is JSON; no network access."""

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .paths import STATE_DIR

UTC = timezone.utc
DEFAULT_DB = STATE_DIR / 'calendar.sqlite3'


def utc_text(value):
    return value.astimezone(UTC).isoformat(timespec='microseconds')


def now_text():
    return utc_text(datetime.now(UTC))


def zone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError('Unknown timezone or missing tzdata; install requirements.txt.') from exc


def instant(value, timezone_name):
    """Reject nonexistent/ambiguous wall times instead of guessing during DST."""
    tz = zone(timezone_name)
    if 'T' not in value and ' ' not in value:
        raise ValueError('Use an ISO date and time, such as 2030-01-15T10:00.')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    candidates = set()
    for fold in (0, 1):
        candidate = parsed.replace(tzinfo=tz, fold=fold).astimezone(UTC)
        if candidate.astimezone(tz).replace(tzinfo=None) == parsed:
            candidates.add(candidate)
    if not candidates:
        raise ValueError('That local time does not exist because of a daylight-saving change.')
    if len(candidates) != 1:
        raise ValueError('That local time is ambiguous; include an explicit UTC offset.')
    return candidates.pop()


def bound(value, timezone_name):
    if 'T' not in value and ' ' not in value:
        value = datetime.combine(date.fromisoformat(value), time()).isoformat()
    return instant(value, timezone_name)


def period(start, end, timezone_name, all_day):
    if all_day:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end) if end else first + timedelta(days=1)
        starts = bound(first.isoformat(), timezone_name)
        ends = bound(last.isoformat(), timezone_name)
        dates = (first.isoformat(), last.isoformat())
    else:
        if not end:
            raise ValueError('Timed appointments require an end time.')
        starts, ends = instant(start, timezone_name), instant(end, timezone_name)
        dates = (None, None)
    if ends <= starts:
        raise ValueError('End must be after start; all-day end dates are exclusive.')
    return utc_text(starts), utc_text(ends), *dates


def leads(values):
    result = sorted(set(values))
    if any(v < 0 for v in result):
        raise ValueError('Reminder lead times must be nonnegative minutes.')
    return result


class Calendar:
    def __init__(self, path, timezone_name=None):
        path = Path(path)
        if timezone_name is None and not path.exists():
            raise ValueError('Calendar is not initialized; run init --timezone first.')
        if timezone_name:
            zone(timezone_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys = ON')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            self.close()
            raise ValueError('Unsupported calendar schema version.')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
                timezone TEXT NOT NULL, all_day INTEGER NOT NULL,
                start_date TEXT, end_date TEXT,
                description TEXT NOT NULL, location TEXT NOT NULL,
                source_ref TEXT NOT NULL, source_key TEXT UNIQUE,
                status TEXT NOT NULL CHECK(status IN ('active', 'cancelled')),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id),
                lead_minutes INTEGER NOT NULL CHECK(lead_minutes >= 0),
                due_at TEXT NOT NULL, delivered_at TEXT,
                UNIQUE(event_id, lead_minutes)
            );
            CREATE INDEX IF NOT EXISTS agenda ON events(status, start_utc, end_utc);
            CREATE INDEX IF NOT EXISTS reminder_due ON reminders(delivered_at, due_at);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id),
                action TEXT NOT NULL, at TEXT NOT NULL, details TEXT NOT NULL
            );
            PRAGMA user_version = 1;
        ''')
        existing = self.db.execute("SELECT value FROM settings WHERE key='timezone'").fetchone()
        if existing and timezone_name and existing['value'] != timezone_name:
            self.close()
            raise ValueError('Calendar already has a timezone; init will not overwrite it.')
        self.timezone = existing['value'] if existing else timezone_name
        if not self.timezone:
            self.close()
            raise ValueError('Calendar has no configured timezone; run init --timezone.')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO settings VALUES ('timezone', ?)", (self.timezone,))

    def close(self):
        self.db.close()

    def event(self, event_id):
        row = self.db.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
        if row is None:
            raise ValueError('Event not found.')
        result = dict(row)
        result['all_day'] = bool(result['all_day'])
        tz = zone(result['timezone'])
        result['start'] = datetime.fromisoformat(result['start_utc']).astimezone(tz).isoformat()
        result['end'] = datetime.fromisoformat(result['end_utc']).astimezone(tz).isoformat()
        result['reminders'] = [dict(r) for r in self.db.execute(
            'SELECT * FROM reminders WHERE event_id=? ORDER BY lead_minutes DESC', (event_id,))]
        return result

    def _audit(self, event_id, action, details):
        self.db.execute('INSERT INTO audit(event_id,action,at,details) VALUES (?,?,?,?)',
                        (event_id, action, now_text(), json.dumps(details, ensure_ascii=False)))

    def _reminders(self, event_id, start, minutes):
        self.db.execute('DELETE FROM reminders WHERE event_id=?', (event_id,))
        for lead in minutes:
            due = utc_text(datetime.fromisoformat(start) - timedelta(minutes=lead))
            self.db.execute('INSERT INTO reminders VALUES (?,?,?,?,NULL)',
                            (str(uuid4()), event_id, lead, due))

    def add(self, title, start, end=None, timezone_name=None, all_day=False,
            description='', location='', source_ref='', source_key=None, reminder_minutes=()):
        if not title.strip():
            raise ValueError('Title cannot be empty.')
        tz = timezone_name or self.timezone
        starts, ends, first, last = period(start, end, tz, all_day)
        minutes = leads(reminder_minutes)
        fields = dict(title=title.strip(), start_utc=starts, end_utc=ends, timezone=tz,
                      all_day=int(all_day), start_date=first, end_date=last,
                      description=description, location=location, source_ref=source_ref)
        event_id, at = str(uuid4()), now_text()
        # Serialize source-key check + insertion, including concurrent ingestion.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            existing = self.db.execute('SELECT * FROM events WHERE source_key=?', (source_key,)).fetchone()
            if existing:
                old_minutes = sorted(r['lead_minutes'] for r in self.event(existing['id'])['reminders'])
                if existing['status'] != 'active' or any(existing[k] != v for k, v in fields.items()) or old_minutes != minutes:
                    raise ValueError('Source already exists with different details; use update explicitly.')
                self.db.commit()
                return {'created': False, 'event': self.event(existing['id'])}
            values = dict(id=event_id, **fields, source_key=source_key, status='active', created_at=at, updated_at=at)
            self.db.execute(f"INSERT INTO events ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
            self._reminders(event_id, starts, minutes)
            self._audit(event_id, 'created', values)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {'created': True, 'event': self.event(event_id)}

    def update(self, event_id, **changes):
        with self.db:
            # Read and write under one write transaction so concurrent updates cannot be lost.
            self.db.execute('BEGIN IMMEDIATE')
            previous = self.event(event_id)
            if previous['status'] != 'active':
                raise ValueError('Cannot update a cancelled event.')
            allowed = {'title', 'start', 'end', 'timezone', 'description', 'location', 'source_ref', 'reminder_minutes'}
            if set(changes) - allowed:
                raise ValueError('Unknown update fields.')
            fields = {key: changes.get(key, previous[key]) for key in ('title', 'description', 'location', 'source_ref', 'timezone')}
            if not fields['title'].strip():
                raise ValueError('Title cannot be empty.')
            fields['title'] = fields['title'].strip()
            if 'timezone' in changes and ('start' not in changes or 'end' not in changes):
                raise ValueError('Timezone changes require explicit start and end values.')
            first = previous['start_date'] if previous['all_day'] else previous['start']
            last = previous['end_date'] if previous['all_day'] else previous['end']
            starts, ends, first, last = period(changes.get('start', first), changes.get('end', last), fields['timezone'], previous['all_day'])
            fields.update(start_utc=starts, end_utc=ends, start_date=first, end_date=last, updated_at=now_text())
            self.db.execute(f"UPDATE events SET {','.join(k+'=?' for k in fields)} WHERE id=?", (*fields.values(), event_id))
            old_minutes = [r['lead_minutes'] for r in previous['reminders']]
            minutes = leads(changes.get('reminder_minutes', old_minutes))
            if starts != previous['start_utc'] or minutes != sorted(old_minutes):
                self._reminders(event_id, starts, minutes)
            self._audit(event_id, 'updated', {'before': previous, 'changes': changes})
        return self.event(event_id)

    def cancel(self, event_id):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            previous = self.event(event_id)
            if previous['status'] == 'active':
                self.db.execute("UPDATE events SET status='cancelled',updated_at=? WHERE id=?", (now_text(), event_id))
                self.db.execute('DELETE FROM reminders WHERE event_id=?', (event_id,))
                self._audit(event_id, 'cancelled', previous)
        return self.event(event_id)

    def agenda(self, start, end):
        starts, ends = utc_text(bound(start, self.timezone)), utc_text(bound(end, self.timezone))
        if ends <= starts:
            raise ValueError('Agenda end must be after start.')
        return [self.event(r['id']) for r in self.db.execute(
            "SELECT id FROM events WHERE status='active' AND start_utc<? AND end_utc>? ORDER BY start_utc,id",
            (ends, starts))]

    def due(self, as_of=None):
        cutoff = utc_text(instant(as_of, self.timezone)) if as_of else now_text()
        # Expired events are not sent as stale notifications after a long offline period.
        return [dict(r) for r in self.db.execute('''
            SELECT r.*,e.title,e.start_utc,e.end_utc,e.timezone,e.all_day,e.source_ref
            FROM reminders r JOIN events e ON e.id=r.event_id
            WHERE r.delivered_at IS NULL AND r.due_at<=? AND e.end_utc>?
                AND e.status='active' ORDER BY r.due_at,r.id
        ''', (cutoff, cutoff))]

    def acknowledge(self, reminder_id):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT * FROM reminders WHERE id=?', (reminder_id,)).fetchone()
            if row is None:
                raise ValueError('Reminder not found (event may have changed or been cancelled).')
            if row['delivered_at'] is None:
                at = now_text()
                self.db.execute('UPDATE reminders SET delivered_at=? WHERE id=?', (at, reminder_id))
                self._audit(row['event_id'], 'reminder_delivered', {'reminder_id': reminder_id})
        return dict(self.db.execute('SELECT * FROM reminders WHERE id=?', (reminder_id,)).fetchone())

    def history(self, event_id):
        self.event(event_id)
        return [dict(r) for r in self.db.execute('SELECT * FROM audit WHERE event_id=? ORDER BY id', (event_id,))]

    def reminder_snapshot(self):
        """Complete reminder projection; the cloud never becomes the calendar writer."""
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute("INSERT OR IGNORE INTO settings VALUES ('reminder_source_id', ?)", (str(uuid4()),))
            source = self.db.execute("SELECT value FROM settings WHERE key='reminder_source_id'").fetchone()[0]
            revision = self.db.execute('SELECT COALESCE(MAX(id),0) FROM audit').fetchone()[0]
            rows = [dict(row) for row in self.db.execute('''
                SELECT r.id,r.event_id,r.lead_minutes,r.due_at,r.delivered_at,
                    e.title,e.start_utc,e.end_utc,e.timezone,e.all_day,e.location
                FROM reminders r JOIN events e ON e.id=r.event_id
                WHERE e.status='active' ORDER BY r.id
            ''')]
        return {'source_id': source, 'revision': revision, 'reminders': rows}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--timezone', required=True)
    add = sub.add_parser('add')
    add.add_argument('--title', required=True)
    add.add_argument('--start', required=True)
    add.add_argument('--end')
    add.add_argument('--timezone', dest='timezone_name')
    add.add_argument('--all-day', action='store_true')
    for field in ('description', 'location', 'source-ref'):
        add.add_argument('--'+field, default='')
    add.add_argument('--source-key')
    add.add_argument('--remind-minutes', type=int, nargs='+', default=[], dest='reminder_minutes')
    update = sub.add_parser('update')
    update.add_argument('id')
    for field in ('title', 'start', 'end', 'timezone', 'description', 'location', 'source-ref'):
        update.add_argument('--'+field)
    group = update.add_mutually_exclusive_group()
    group.add_argument('--remind-minutes', type=int, nargs='+', dest='reminder_minutes')
    group.add_argument('--clear-reminders', action='store_true')
    agenda = sub.add_parser('agenda')
    agenda.add_argument('--from', required=True, dest='start')
    agenda.add_argument('--to', required=True, dest='end')
    for command in ('get', 'cancel', 'history'):
        sub.add_parser(command).add_argument('id')
    sub.add_parser('due').add_argument('--as-of')
    sub.add_parser('ack-reminder').add_argument('id')
    args = vars(parser.parse_args(argv))
    command, path = args.pop('command'), args.pop('db')
    calendar = None
    try:
        calendar = Calendar(path, args['timezone'] if command == 'init' else None)
        if command == 'init':
            result = {'database': str(path.resolve()), 'timezone': calendar.timezone, 'ready': True}
        elif command == 'update':
            event_id = args.pop('id')
            clear = args.pop('clear_reminders')
            changes = {k: v for k, v in args.items() if v is not None}
            if clear:
                changes['reminder_minutes'] = []
            if not changes:
                raise ValueError('Specify at least one field to update.')
            result = calendar.update(event_id, **changes)
        elif command in ('get', 'cancel', 'history'):
            method = calendar.event if command == 'get' else getattr(calendar, command)
            result = method(args['id'])
        elif command == 'ack-reminder':
            result = calendar.acknowledge(args['id'])
        else:
            result = getattr(calendar, command)(**args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if calendar:
            calendar.close()


if __name__ == '__main__':
    sys.exit(main())
