import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from assistant_calendar import Calendar, instant


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'calendar.sqlite3'
        self.calendar = Calendar(self.path, 'Europe/Berlin')

    def tearDown(self):
        self.calendar.close()
        self.temp.cleanup()

    def add(self, **kwargs):
        return self.calendar.add('Test appointment', '2030-01-15T10:00', '2030-01-15T11:00', **kwargs)['event']

    def test_persistence_and_overlap(self):
        event = self.add()
        self.calendar.close()
        self.calendar = Calendar(self.path)
        self.assertEqual(self.calendar.timezone, 'Europe/Berlin')
        self.assertEqual(self.calendar.event(event['id'])['start'], '2030-01-15T10:00:00+01:00')
        self.assertEqual([r['id'] for r in self.calendar.agenda('2030-01-15T10:30', '2030-01-15T11:30')], [event['id']])
        self.assertEqual(self.calendar.agenda('2030-01-15T11:00', '2030-01-15T12:00'), [])

    def test_entrypoints_share_relocated_state_from_other_directory(self):
        root = Path(__file__).resolve().parents[1]
        relocated = Path(self.temp.name) / 'runtime'
        environment = {**os.environ, 'ASSISTANT_STATE_DIR': str(relocated),
                       'PYTHONPATH': str(root / 'src')}
        def invoke(arguments):
            result = subprocess.run([sys.executable, *arguments], cwd=self.temp.name,
                                    env=environment, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        initialized = invoke([str(root / 'assistant_calendar.py'), 'init', '--timezone', 'Europe/Berlin'])
        self.assertEqual(Path(initialized['database']), relocated / 'calendar.sqlite3')
        added = invoke(['-m', 'personal_assistant.calendar', 'add', '--title', 'Isolated event',
                        '--start', '2030-01-15T10:00', '--end', '2030-01-15T11:00'])
        agenda = invoke([str(root / 'assistant_calendar.py'), 'agenda',
                         '--from', '2030-01-15', '--to', '2030-01-16'])
        self.assertEqual([event['id'] for event in agenda], [added['event']['id']])

    def test_dst_gap_and_fold_require_clarity(self):
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            instant('2026-03-29T02:30', 'Europe/Berlin')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            instant('2026-10-25T02:30', 'Europe/Berlin')
        first = instant('2026-10-25T02:30+02:00', 'Europe/Berlin')
        second = instant('2026-10-25T02:30+01:00', 'Europe/Berlin')
        self.assertEqual(second-first, timedelta(hours=1))

    def test_all_day_preserves_dates_on_dst_boundary(self):
        event = self.calendar.add('All day', '2026-03-29', all_day=True)['event']
        self.assertEqual(event['start_date'], '2026-03-29')
        self.assertEqual(event['end_date'], '2026-03-30')
        self.assertEqual(datetime.fromisoformat(event['end_utc']) - datetime.fromisoformat(event['start_utc']), timedelta(hours=23))
        self.assertEqual(len(self.calendar.agenda('2026-03-29', '2026-03-30')), 1)
        self.assertEqual(self.calendar.agenda('2026-03-30', '2026-03-31'), [])

    def test_duplicate_ingestion_and_conflicting_source(self):
        first = self.add(source_key='test:message:1', reminder_minutes=[60])
        second = self.calendar.add('Test appointment', '2030-01-15T10:00', '2030-01-15T11:00', source_key='test:message:1', reminder_minutes=[60])
        self.assertFalse(second['created'])
        self.assertEqual(first['id'], second['event']['id'])
        with self.assertRaisesRegex(ValueError, 'different details'):
            self.calendar.add('Changed', '2030-01-15T10:00', '2030-01-15T11:00', source_key='test:message:1')
        self.assertEqual(len(self.calendar.agenda('2030-01-15', '2030-01-16')), 1)

    def test_concurrent_ingestion_is_idempotent(self):
        def ingest(_):
            worker = Calendar(self.path)
            try:
                return worker.add('Concurrent', '2030-01-15T10:00', '2030-01-15T11:00', source_key='test:concurrent')
            finally:
                worker.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(ingest, range(2)))
        self.assertEqual(sum(r['created'] for r in results), 1)
        self.assertEqual(results[0]['event']['id'], results[1]['event']['id'])

    def test_move_reminder_acknowledge_and_cancel(self):
        event = self.add(reminder_minutes=[60])
        old_id = event['reminders'][0]['id']
        self.assertEqual(len(self.calendar.due('2030-01-15T09:30')), 1)
        updated = self.calendar.update(event['id'], start='2030-01-16T10:00', end='2030-01-16T11:00')
        self.assertEqual(self.calendar.due('2030-01-15T09:30'), [])
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.calendar.acknowledge(old_id)
        reminder = self.calendar.due('2030-01-16T09:30')[0]
        self.calendar.acknowledge(reminder['id'])
        self.assertEqual(self.calendar.due('2030-01-16T09:30'), [])
        # Editing a title must not reset delivery and cause a duplicate notification.
        self.calendar.update(event['id'], title='Edited title')
        self.assertEqual(self.calendar.due('2030-01-16T09:30'), [])
        self.calendar.cancel(event['id'])
        self.calendar.cancel(event['id'])
        self.assertEqual(self.calendar.agenda('2030-01-16', '2030-01-17'), [])
        history = self.calendar.history(event['id'])
        self.assertEqual([h['action'] for h in history], ['created', 'updated', 'reminder_delivered', 'updated', 'cancelled'])
        self.assertEqual(updated['start'], '2030-01-16T10:00:00+01:00')

    def test_cancel_discards_pending_reminders_and_blocks_reimport(self):
        event = self.add(source_key='test:cancelled', reminder_minutes=[60])
        self.calendar.cancel(event['id'])
        self.assertEqual(self.calendar.due('2030-01-15T09:30'), [])
        with self.assertRaisesRegex(ValueError, 'different details'):
            self.add(source_key='test:cancelled', reminder_minutes=[60])

    def test_validation_rolls_back_event_and_audit(self):
        event = self.add()
        with self.assertRaises(ValueError):
            self.calendar.update(event['id'], title='Should not persist', reminder_minutes=[-1])
        self.assertEqual(self.calendar.event(event['id'])['title'], 'Test appointment')
        self.assertEqual(len(self.calendar.history(event['id'])), 1)
        with self.assertRaises(ValueError):
            self.calendar.add('Bad', '2030-01-15T11:00', '2030-01-15T10:00')
        with self.assertRaises(ValueError):
            self.calendar.add('Bad', '2030-01-15T11:00')

    def test_offline_recovery_does_not_deliver_expired_events(self):
        self.add(reminder_minutes=[60, 1440])
        self.assertEqual(self.calendar.due('2030-01-15T12:00'), [])

    def test_init_does_not_change_existing_timezone(self):
        with self.assertRaisesRegex(ValueError, 'will not overwrite'):
            Calendar(self.path, 'UTC')
        self.assertEqual(self.calendar.timezone, 'Europe/Berlin')

    def test_cli_roundtrip_and_structured_error(self):
        script = Path(__file__).resolve().parents[1] / 'assistant_calendar.py'
        def command(*args):
            return subprocess.run([sys.executable, str(script), '--db', str(self.path), *args], capture_output=True, text=True, encoding='utf-8')
        added = command('add', '--title', 'Calendar CLI', '--start', '2030-01-15T10:00', '--end', '2030-01-15T11:00')
        self.assertEqual(added.returncode, 0, added.stderr)
        event_id = json.loads(added.stdout)['event']['id']
        self.assertEqual(json.loads(command('get', event_id).stdout)['title'], 'Calendar CLI')
        error = command('add', '--title', 'Bad', '--start', '2030-01-15T10:00')
        self.assertEqual(error.returncode, 1)
        self.assertIn('error', json.loads(error.stderr))


if __name__ == '__main__':
    unittest.main()
