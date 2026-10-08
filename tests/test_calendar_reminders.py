import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from personal_assistant.calendar import Calendar
from personal_assistant.relay.reminders import ReminderStore, ReminderPump, epoch, reminder_router


class CalendarReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.calendar = Calendar(self.path/'local.db', 'Europe/Berlin')
        self.now = epoch('2030-01-15T08:29:00+00:00')
        self.store = ReminderStore(self.path/'cloud.db', clock=lambda: self.now)
        self.sent = []
        self.pump = ReminderPump(self.store, self.sent.append)

    def tearDown(self):
        self.calendar.close()
        self.temp.cleanup()

    def appointment(self):
        return self.calendar.add('Appointment', '2030-01-15T10:00', '2030-01-15T11:00',
                                 reminder_minutes=[30])['event']

    def sync(self):
        return self.store.project(self.calendar.reminder_snapshot())

    def test_cloud_delivery_after_local_disconnect_and_restart(self):
        event = self.appointment()
        self.sync()
        self.pump.tick()
        self.assertEqual(self.sent, [])
        self.now += 60
        self.calendar.close()  # Laptop disappears; projected reminder still arrives.
        self.pump.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('10:00', self.sent[0]['message'])
        self.assertEqual(self.sent[0]['data']['tag'], 'assistant-calendar-'+event['reminders'][0]['id'])
        self.calendar = Calendar(self.path/'local.db')
        restarted = ReminderStore(self.path/'cloud.db', clock=lambda: self.now)
        ReminderPump(restarted, self.sent.append).tick()
        self.sync()
        self.pump.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(restarted.receipts()), 1)

    def test_moving_and_cancelling_remove_old_occurrences(self):
        event = self.appointment()
        self.sync()
        changed = self.calendar.update(event['id'], start='2030-01-15T12:00', end='2030-01-15T13:00')
        self.assertNotEqual(event['reminders'][0]['id'], changed['reminders'][0]['id'])
        self.sync()
        self.now += 60
        self.pump.tick()
        self.assertEqual(self.sent, [])
        self.calendar.cancel(event['id'])
        self.sync()
        self.now = epoch('2030-01-15T11:00:00+00:00')
        self.pump.tick()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.status()['counts'], {})

    def test_stale_same_revision_and_other_source_rejected(self):
        self.appointment()
        original = self.calendar.reminder_snapshot()
        self.store.project(original)
        self.assertFalse(self.store.project(copy.deepcopy(original))['changed'])
        tampered = copy.deepcopy(original)
        tampered['reminders'][0]['title'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'different contents'):
            self.store.project(tampered)
        event = self.calendar.agenda('2030-01-15', '2030-01-16')[0]
        self.calendar.update(event['id'], title='New title')
        self.sync()
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.store.project(original)
        tampered['source_id'] = '00000000-0000-0000-0000-000000000000'
        with self.assertRaisesRegex(ValueError, 'another calendar'):
            self.store.project(tampered)

    def test_retry_durable_and_updates_preserve_delivery(self):
        event = self.appointment()
        self.sync()
        self.now += 60
        failures = []
        def fail(payload):
            failures.append(payload)
            raise TimeoutError()
        ReminderPump(self.store, fail).tick()
        self.pump.tick()
        self.assertEqual(self.sent, [])
        self.now += 2
        restarted = ReminderStore(self.path/'cloud.db', clock=lambda: self.now)
        ReminderPump(restarted, self.sent.append).tick()
        self.assertEqual(len(self.sent), 1)
        self.calendar.update(event['id'], title='Updated appointment', end='2030-01-15T11:30')
        self.sync()
        self.pump.tick()
        self.assertEqual(len(self.sent), 1)

    def test_expired_events_and_same_id_time_reuse(self):
        self.appointment()
        snapshot = self.calendar.reminder_snapshot()
        self.store.project(snapshot)
        self.now = epoch('2030-01-15T10:00:00+00:00')
        self.pump.tick()
        self.assertEqual(self.sent, [])
        snapshot['revision'] += 1
        snapshot['reminders'][0]['due_at'] = '2030-01-15T08:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'reused'):
            self.store.project(snapshot)

    def test_delivery_lease_prevents_concurrent_sender_and_recovers_crash(self):
        self.appointment()
        self.sync()
        self.now += 60
        row = self.store.due()[0]
        self.assertTrue(self.store.claim(row['id'], row['payload']))
        self.pump.tick()
        self.assertEqual(self.sent, [])
        self.now += 30  # Claimed process crashed before transport; lease safely expires.
        competing = ReminderPump(self.store, self.sent.append)
        def send(payload):
            competing.tick()
            self.sent.append(payload)
        ReminderPump(self.store, send).tick()
        self.assertEqual(len(self.sent), 1)

    def test_api_authentication_and_local_receipt_reconciliation(self):
        self.appointment()
        app = FastAPI()
        def owner(authorization: str | None = Header(default=None)):
            if authorization != 'Bearer owner':
                raise HTTPException(401)
        def worker(authorization: str | None = Header(default=None)):
            if authorization != 'Bearer worker':
                raise HTTPException(401)
        app.include_router(reminder_router(self.store, owner, worker))
        client = TestClient(app)
        snapshot = self.calendar.reminder_snapshot()
        endpoint = '/v1/calendar/reminders/snapshot'
        self.assertEqual(client.post(endpoint, json=snapshot).status_code, 401)
        self.assertEqual(client.post(endpoint, json=snapshot, headers={'Authorization':'Bearer owner'}).status_code, 401)
        self.assertEqual(client.post(endpoint, json=snapshot, headers={'Authorization':'Bearer worker'}).status_code, 200)
        self.now += 60
        self.pump.tick()
        spec = importlib.util.spec_from_file_location('calendar_sync_script', Path(__file__).resolve().parents[1]/'scripts/sync_calendar_reminders.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        store = self.store
        class FakeClient:
            def call(self, path, payload=None):
                return store.project(payload) if payload else {'receipts': store.receipts()}
        self.assertEqual(script.synchronize(self.path/'local.db', FakeClient())['acknowledged'], 1)
        self.assertEqual(script.synchronize(self.path/'local.db', FakeClient())['acknowledged'], 0)
        self.assertEqual(len(self.store.receipts()), 1)


if __name__ == '__main__':
    unittest.main()
