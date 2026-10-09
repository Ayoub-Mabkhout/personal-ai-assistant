import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from fastapi.testclient import TestClient
from personal_assistant.groceries.mobile import Devices
from personal_assistant.relay.api import create_app
from personal_assistant.relay.delivery import resolve_mode
from personal_assistant.relay.mobile_push import CompanionSender, FcmError, FcmPush, MobileEventStore, MobilePushPump, fcm_code
from personal_assistant.relay.notifications import NotificationPump, notification
from personal_assistant.relay.preflight import check, main as preflight
from personal_assistant.relay.reminders import ReminderPump, ReminderStore, epoch
from personal_assistant.relay.store import Queue

OWNER = 'o' * 40
TOKEN = 'registration-token-' * 4


def http_error(code, body=None):
    return urllib.error.HTTPError('https://example.test/send', code, 'failure', {}, None if body is None else io.BytesIO(
        body if isinstance(body, bytes) else json.dumps(body).encode()))


def fcm_body(code=None, status=None):
    error = {'code': 400, 'message': 'secret ' + TOKEN}
    if status:
        error['status'] = status
    if code:
        error['details'] = [{'@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError', 'errorCode': code}]
    return {'error': error}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = [1900000000.0]
        self.legacy = []
        self.hints = []

    def tearDown(self):
        self.temp.cleanup()

    def clock(self):
        return self.now[0]

    def config(self, **values):
        return {'enabled': True, 'public_url': 'https://assistant.example.test', 'native_provider': lambda row: self.hints.append(row['id']), **values}

    def app(self, notifications, groceries=True):
        extra = {'groceries': {'path': self.root/'groceries.sqlite3', 'internal_token': 'g' * 40,
                               'assets': self.root}} if groceries else {}
        return create_app(self.root/'queue.sqlite3', OWNER, 'w' * 40, clock=self.clock, notifications=notifications, **extra)

    def phone(self, app, token=TOKEN):
        devices = app.state.mobile_events.devices
        phone = devices.exchange(devices.pairing()['code'], 'Phone')
        if token:
            app.state.mobile_events.register(phone['id'], 'fcm', token)
        return phone

    def submit(self, client, identifier='task-handover-1'):
        return client.post('/v1/agent/prompts', headers={'Authorization': 'Bearer ' + OWNER},
                           json={'id': identifier, 'prompt': 'Sentinel request text'})

    def events(self, app, phone):
        return app.state.mobile_events.events(phone['id'])['items']

    def store(self, name='phones.sqlite3'):
        return MobileEventStore(Devices(self.root/name, clock=self.clock))

    def provider(self, requester, signer=lambda body: b'signature'):
        account = self.root/'account.json'
        account.write_text(json.dumps({'type': 'service_account', 'project_id': 'demo-project',
                                       'client_email': 'sender@example.test', 'private_key': 'test'}))
        return FcmPush({'service_account_file': str(account)}, requester=requester, signer=signer, clock=self.clock)






class ModeWiringTests(Fixture):
    def publish_release(self, client):
        apk = self.root/'companion.apk'
        apk.write_bytes(b'test-apk')
        digest = hashlib.sha256(b'test-apk').hexdigest()
        apk.with_suffix('.release.json').write_text(json.dumps({'package_name': 'com.personalassistant.companion', 'version_code': 3,
            'version_name': '0.3.0', 'min_sdk': 26, 'size': apk.stat().st_size, 'sha256': digest}))
        response = client.post('/groceries/v1/mobile/release/published', json={'version_code': 3, 'sha256': digest},
                               headers={'Authorization': 'Bearer ' + 'g' * 40})
        self.assertEqual(response.status_code, 200)

    def deliver_everything(self, mode):
        """A reminder, an alarm request and a release hint through the app that the relay builds for the mode."""
        app = self.app(self.config(delivery_mode=mode))
        phone = self.phone(app)
        client = TestClient(app)
        due = lambda offset: datetime.fromtimestamp(self.now[0] + offset, timezone.utc).isoformat(timespec='seconds')
        ReminderStore(self.root/'reminders.sqlite3', clock=self.clock).project({
            'source_id': '00000000-0000-4000-8000-000000000001', 'revision': 1, 'reminders': [{
                'id': '00000000-0000-4000-8000-000000000002', 'event_id': '00000000-0000-4000-8000-000000000003', 'lead_minutes': 30,
                'due_at': due(-60), 'delivered_at': None, 'title': 'Appointment', 'start_utc': due(1800), 'end_utc': due(5400),
                'timezone': 'UTC', 'all_day': 0, 'location': ''}]})
        app.state.reminder_pump.tick()
        alarm = client.post('/groceries/v1/mobile/alarms', headers={'Authorization': 'Bearer ' + 'g' * 40},
                            json={'id': 'alarm-wiring-1', 'phone': phone['id'], 'hour': 7, 'minute': 30, 'label': 'Wake'})
        self.assertTrue(alarm.json()['push_api_accepted'])
        self.publish_release(client)
        app.state.release_pump.tick()
        return sorted(event['payload']['type'] for event in self.events(app, phone))


    def test_native_mode_delivers_reminders_alarms_and_release_hints_only_natively(self):
        self.assertEqual(self.deliver_everything('native'), ['alarm', 'release', 'reminder'])
        self.assertEqual(self.legacy, [])


class NativeBacklogTests(Fixture):
    def setup_queue(self):
        queue = Queue(self.root/'agent.sqlite3', clock=self.clock, serial=True, notifications=True)
        devices = Devices(self.root/'phones.sqlite3', clock=self.clock)
        store = MobileEventStore(devices)
        return queue, devices, store

    def test_zero_phones_raises_for_every_event_type_so_producers_retry(self):
        sender = CompanionSender(self.store())
        for payload in ({'title': 'Calendar reminder', 'message': 'x', 'data': {'tag': 'assistant-calendar-abc'}},
                        {'title': 'Phone alarm request', 'message': 'x', 'data': {'tag': 'assistant-alarm-abc', 'phone_id': 'absent'}},
                        {'type': 'release', 'data': {'version_code': 1, 'sha256': '1' * 64}}):
            with self.assertRaisesRegex(OSError, 'No active paired Companion'):
                sender(payload)

    def test_task_waits_for_the_first_phone_instead_of_reporting_success(self):
        queue, devices, store = self.setup_queue()
        pump = NotificationPump({'agent': queue}, CompanionSender(store), 'https://assistant.example.test')
        queue.submit({'id': 'task-waiting-1', 'command': 'Question', 'timezone': 'UTC'})
        pump.tick()
        row = queue.notification_rows()[0]
        self.assertEqual((row['delivered_revision'], row['attempts']), (0, 1))
        phone = devices.exchange(devices.pairing()['code'], 'Phone')
        self.now[0] += 6
        pump.tick()
        self.assertEqual(len(store.events(phone['id'])['items']), 1)

    def test_reminder_waits_for_the_first_phone(self):
        reminders = ReminderStore(self.root/'reminders.sqlite3', clock=self.clock)
        store = self.store()
        self.now[0] = epoch('2030-01-15T08:29:00+00:00')
        due = '2030-01-15T08:30:00+00:00'
        reminders.project({'source_id': '00000000-0000-4000-8000-000000000001', 'revision': 1, 'reminders': [{
            'id': '00000000-0000-4000-8000-000000000002', 'event_id': '00000000-0000-4000-8000-000000000003', 'lead_minutes': 30, 'due_at': due, 'delivered_at': None,
            'title': 'Appointment', 'start_utc': '2030-01-15T09:00:00+00:00', 'end_utc': '2030-01-15T10:00:00+00:00',
            'timezone': 'UTC', 'all_day': 0, 'location': ''}]})
        pump = ReminderPump(reminders, CompanionSender(store))
        self.now[0] += 120
        pump.tick()
        self.assertEqual(reminders.receipts(), [])
        phone = store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        self.now[0] += 10
        pump.tick()
        self.assertEqual(len(reminders.receipts()), 1)
        self.assertEqual(store.events(phone['id'])['items'][0]['payload']['type'], 'reminder')

    def test_age_cap_keeps_first_pairing_from_backfilling_old_final_cards(self):
        queue, devices, store = self.setup_queue()
        pump = NotificationPump({'agent': queue}, CompanionSender(store), 'https://assistant.example.test', max_age=3600)
        queue.heartbeat('ready')
        queue.submit({'id': 'task-old-final', 'command': 'Old', 'timezone': 'UTC'})
        job = queue.claim()
        queue.finish(job['id'], job['lease_token'], 'completed', {'summary': 'Done'})
        queue.submit({'id': 'task-still-queued', 'command': 'Waiting', 'timezone': 'UTC'})
        pump.tick()
        self.now[0] += 7200
        queue.heartbeat('ready')
        queue.submit({'id': 'task-recent-final', 'command': 'Recent', 'timezone': 'UTC'})
        queue.cancel('task-recent-final')
        phone = devices.exchange(devices.pairing()['code'], 'Phone')
        self.now[0] += 400
        pump.tick()
        tags = sorted(event['payload']['tag'] for event in store.events(phone['id'])['items'])
        self.assertEqual(tags, ['assistant-agent-task-recent-final', 'assistant-agent-task-still-queued'])
        self.assertEqual([row['job_id'] for row in queue.notification_rows()], ['task-still-queued'])

    def test_age_cap_counts_from_the_final_state_so_long_tasks_still_report_completion(self):
        queue, devices, store = self.setup_queue()
        pump = NotificationPump({'agent': queue}, CompanionSender(store), 'https://assistant.example.test', max_age=3600)
        phone = devices.exchange(devices.pairing()['code'], 'Phone')
        queue.heartbeat('ready')
        queue.submit({'id': 'task-long-running', 'command': 'Long', 'timezone': 'UTC'})
        job = queue.claim(lease_seconds=300)
        pump.tick()
        for _ in range(30):
            self.now[0] += 250
            queue.renew(job['id'], job['lease_token'], lease_seconds=300)
        queue.finish(job['id'], job['lease_token'], 'completed', {'summary': 'Done'})
        pump.tick()
        self.assertEqual([event['payload']['active'] for event in store.events(phone['id'])['items']], [True, False])



class JournalTests(Fixture):
    def test_state_returning_to_an_earlier_value_is_delivered_again(self):
        store = self.store()
        phone = store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        first, second = ({'type': 'task', 'tag': 'assistant-agent-task-1', 'message': text} for text in ('Offline', 'Working'))
        for payload in (first, second, first, first):
            store.enqueue(payload)
        items = store.events(phone['id'])['items']
        self.assertEqual([item['payload']['message'] for item in items], ['Offline', 'Working', 'Offline'])
        self.assertEqual(len({item['id'] for item in items}), 3)

    def test_returning_state_through_the_task_pump_and_idempotent_retry(self):
        queue = Queue(self.root/'agent.sqlite3', clock=self.clock, serial=True, notifications=True)
        store = self.store()
        phone = store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        pump = NotificationPump({'agent': queue}, CompanionSender(store), 'https://assistant.example.test')
        queue.submit({'id': 'task-flapping-1', 'command': 'Question', 'timezone': 'UTC'})
        pump.tick()
        queue.heartbeat('ready')
        pump.tick()
        self.now[0] += 61
        pump.tick()
        pump.tick()
        items = store.events(phone['id'])['items']
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]['payload']['message'], items[2]['payload']['message'])
        self.assertNotEqual(items[0]['payload']['message'], items[1]['payload']['message'])

    def test_producer_retry_is_matched_per_tag_even_when_other_tags_interleave(self):
        store = self.store()
        phone = store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        one, two = ({'type': 'task', 'tag': 'assistant-agent-task-' + number, 'message': 'Working'} for number in ('1', '2'))
        for payload in (one, two, one, two):
            store.enqueue(payload)
        self.assertEqual(len(store.events(phone['id'])['items']), 2)

    def test_producer_retry_is_matched_however_long_the_history_since(self):
        store = self.store()
        phone = store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        first = {'type': 'task', 'tag': 'assistant-agent-task-1', 'message': 'Working'}
        store.enqueue(first)
        for number in range(250):
            store.enqueue({'type': 'task', 'tag': 'assistant-agent-other-%d' % number, 'message': 'Other'})
        store.enqueue(first)
        self.assertEqual(len(store.events(phone['id'], limit=500)['items']), 251)

    def test_the_same_repeat_key_on_different_tasks_is_one_event_each(self):
        store = self.store()
        phone = store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        for number in ('1', '2', '1', '2'):
            store.enqueue({'type': 'task', 'tag': 'assistant-agent-task-' + number, 'message': 'Same'}, repeat='revision-2')
        self.assertEqual(len(store.events(phone['id'])['items']), 2)

    def test_explicit_repeat_is_new_once_and_idempotent_per_key(self):
        store = self.store()
        phone = store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        payload = {'type': 'task', 'tag': 'assistant-agent-task-1', 'message': 'Same'}
        store.enqueue(payload)
        store.enqueue(payload, repeat='revision-7')
        store.enqueue(payload, repeat='revision-7')
        self.assertEqual(len(store.events(phone['id'])['items']), 2)
        store.enqueue(payload)
        self.assertEqual(len(store.events(phone['id'])['items']), 2)


    def test_notify_again_works_in_native_mode(self):
        app = self.app(self.config(delivery_mode='native'))
        phone = self.phone(app)
        client = TestClient(app)
        self.submit(client)
        app.state.notification_pump.tick()
        client.post('/v1/agent/prompts/task-handover-1/notify', headers={'Authorization': 'Bearer ' + OWNER})
        app.state.notification_pump.tick()
        app.state.notification_pump.tick()
        self.assertEqual(len(self.events(app, phone)), 2)

    def test_previous_image_statements_still_work_on_the_migrated_database(self):
        store = self.store()
        phone = store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        store.register(phone['id'], 'fcm', TOKEN)
        store.enqueue({'type': 'task', 'message': 'Current image'})
        with contextlib.closing(sqlite3.connect(self.root/'phones.sqlite3')) as db:
            columns = [row[1] for row in db.execute('PRAGMA table_info(native_push)')]
            self.assertEqual(columns, ['phone', 'provider', 'token', 'updated'])
            db.execute('INSERT INTO native_push VALUES(?,?,?,?) ON CONFLICT(phone) DO UPDATE SET provider=excluded.provider,token=excluded.token,updated=excluded.updated',
                       (phone['id'], 'fcm', 'rotated-' + TOKEN, 1.0))
            db.execute('''INSERT OR IGNORE INTO native_events(id,phone,fingerprint,payload,created,expires,due)
                       VALUES(?,?,?,?,?,?,?)''', ('previous-image-event', phone['id'], 'previous-fingerprint', '{}', 1.0, 9e9, 1.0))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM native_events').fetchone()[0], 2)

    def test_database_written_by_the_previous_image_is_read_and_extended(self):
        path = self.root/'phones.sqlite3'
        devices = Devices(path, clock=self.clock)
        phone = devices.exchange(devices.pairing()['code'], 'Phone')
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.executescript('''CREATE TABLE native_push (phone TEXT PRIMARY KEY,provider TEXT NOT NULL,token TEXT NOT NULL,updated REAL NOT NULL);
                CREATE TABLE native_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,phone TEXT NOT NULL,
                fingerprint TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,
                accepted REAL,received REAL,attempts INTEGER NOT NULL DEFAULT 0,due REAL NOT NULL,UNIQUE(phone,fingerprint));''')
            db.execute('INSERT INTO native_events(id,phone,fingerprint,payload,created,expires,due) VALUES(?,?,?,?,?,?,?)',
                       ('legacy-event', phone['id'], 'legacy-fingerprint', json.dumps({'type': 'task', 'tag': 'assistant-agent-task-1', 'message': 'Old'}),
                        self.now[0], self.now[0] + 100, self.now[0]))
            db.commit()
        store = MobileEventStore(devices)
        store.enqueue({'type': 'task', 'tag': 'assistant-agent-task-1', 'message': 'New'})
        self.assertEqual([item['payload']['message'] for item in store.events(phone['id'])['items']], ['Old', 'New'])


class FcmErrorTests(Fixture):
    def test_fcm_rejections_are_classified_from_the_error_detail_or_the_status(self):
        cases = [(404, fcm_body('UNREGISTERED', 'NOT_FOUND'), 'UNREGISTERED'),
                 (404, fcm_body(None, 'NOT_FOUND'), 'NOT_FOUND'),
                 (400, fcm_body('INVALID_ARGUMENT'), 'INVALID_ARGUMENT'),
                 (403, fcm_body('SENDER_ID_MISMATCH', 'PERMISSION_DENIED'), 'SENDER_ID_MISMATCH'),
                 (403, fcm_body(None, 'PERMISSION_DENIED'), 'PERMISSION_DENIED'),
                 (429, fcm_body('QUOTA_EXCEEDED'), 'QUOTA_EXCEEDED'),
                 (429, fcm_body(None, 'RESOURCE_EXHAUSTED'), 'QUOTA_EXCEEDED'),
                 (401, fcm_body('THIRD_PARTY_AUTH_ERROR'), 'THIRD_PARTY_AUTH_ERROR'),
                 (503, fcm_body('UNAVAILABLE'), 'UNAVAILABLE'),
                 (500, b'<html>gateway</html>', 'UNAVAILABLE'),
                 (418, None, 'HTTP_418')]
        for status, body, code in cases:
            self.assertEqual(fcm_code(http_error(status, body)), code, (status, body))

    def test_odd_response_bodies_fall_back_to_the_status_without_echoing_them(self):
        for body in ([1, 2], '"UNREGISTERED"', 7, {'error': ['UNREGISTERED']}, {'error': {'details': 'UNREGISTERED'}},
                     {'error': {'details': [None, 5, {'errorCode': {'x': []}}], 'status': ['NOT_FOUND']}},
                     {'error': {'details': [{'errorCode': 'surprise-' + TOKEN}]}}, b'\xff\xfe', b''):
            self.assertEqual(fcm_code(http_error(404, body)), 'NOT_FOUND', body)
        self.assertEqual(fcm_code(http_error(404)), 'NOT_FOUND')

    def test_error_bodies_are_read_with_a_bound(self):
        sizes = []

        class Body(io.BytesIO):
            def read(self, size=-1):
                sizes.append(size)
                return super().read(size)
        self.assertEqual(fcm_code(urllib.error.HTTPError('https://example.test/send', 500, 'failure', {}, Body(b'x' * 100000))), 'UNAVAILABLE')
        self.assertEqual(sizes, [4096])

    def test_oauth_failures_are_distinct_from_fcm_send_failures(self):
        self.assertEqual(fcm_code(http_error(400, {'error': 'invalid_grant', 'error_description': 'Invalid JWT'}), True), 'OAUTH_INVALID_GRANT')
        self.assertEqual(fcm_code(http_error(400, [1]), True), 'OAUTH_INVALID_ARGUMENT')
        self.assertEqual(fcm_code(http_error(502), True), 'OAUTH_UNAVAILABLE')

        def reject(url, body, headers):
            raise http_error(400, {'error': 'invalid_client'}) if url.endswith('/token') else AssertionError()
        with self.assertRaises(FcmError) as caught:
            self.provider(reject)({'id': 'e', 'token': TOKEN, 'expires': self.now[0] + 60})
        self.assertEqual(caught.exception.code, 'OAUTH_INVALID_CLIENT')

        def offline(url, body, headers):
            raise urllib.error.URLError('network down ' + TOKEN)
        with self.assertRaises(FcmError) as caught:
            self.provider(offline).bearer()
        self.assertEqual(str(caught.exception), 'OAUTH_UNREACHABLE')

        def bad_key(body):
            raise ValueError('unparseable key')
        with self.assertRaises(FcmError) as caught:
            self.provider(lambda *args: {}, signer=bad_key).bearer()
        self.assertEqual(caught.exception.code, 'OAUTH_CREDENTIAL')

    def test_send_failures_carry_only_the_code_and_a_401_refreshes_the_token(self):
        tokens = []
        def request(url, body, headers):
            if url.endswith('/token'):
                tokens.append(1)
                return {'access_token': 'mock-access', 'expires_in': 3600}
            raise http_error(401, fcm_body(None, 'UNAUTHENTICATED'))
        push = self.provider(request)
        for _ in range(2):
            with self.assertRaises(FcmError) as caught:
                push({'id': 'e', 'token': TOKEN, 'expires': self.now[0] + 60})
            self.assertEqual(str(caught.exception), 'UNAUTHENTICATED')
            self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(len(tokens), 2)

        def unreachable(url, body, headers):
            if url.endswith('/token'):
                return {'access_token': 'mock-access', 'expires_in': 3600}
            raise TimeoutError()
        with self.assertRaises(FcmError) as caught:
            self.provider(unreachable)({'id': 'e', 'token': TOKEN, 'expires': self.now[0] + 60})
        self.assertEqual(caught.exception.code, 'UNREACHABLE')
        def garbled(url, body, headers):
            if url.endswith('/token'):
                return {'access_token': 'mock-access', 'expires_in': 3600}
            raise ValueError('not json ' + TOKEN)
        with self.assertRaises(FcmError) as caught:
            self.provider(garbled)({'id': 'e', 'token': TOKEN, 'expires': self.now[0] + 60})
        self.assertEqual(caught.exception.code, 'BAD_RESPONSE')
        for answer, code in (({}, 'NO_ACK'), ({'name': 5}, 'NO_ACK'), ([], 'NO_ACK')):
            with self.assertRaises(FcmError) as caught:
                self.provider(lambda url, body, headers, answer=answer: {'access_token': 'a', 'expires_in': 9} if url.endswith('/token') else answer)(
                    {'id': 'e', 'token': TOKEN, 'expires': self.now[0] + 60})
            self.assertEqual(caught.exception.code, code)


class PushHealthTests(Fixture):
    def registered(self):
        store = self.store()
        phone = store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        store.register(phone['id'], 'fcm', TOKEN)
        store.enqueue({'type': 'task', 'message': 'Private answer'})
        return store, phone

    def fail_with(self, store, code):
        def provider(row):
            raise FcmError(code)
        with self.assertLogs(level='WARNING') as logs:
            MobilePushPump(store, provider).tick()
        self.assertNotIn(TOKEN, ''.join(logs.output))
        return logs.output[0]

    def test_unregistered_deletes_the_dead_token_and_records_the_code(self):
        store, phone = self.registered()
        self.assertIn('UNREGISTERED', self.fail_with(store, 'UNREGISTERED'))
        self.assertFalse(store.status(phone['id'])['registered'])
        health = store.overview()['phones'][0]
        self.assertEqual(health['last_error']['code'], 'UNREGISTERED')
        self.assertFalse(health['registered'])
        self.now[0] += 11
        self.assertEqual(store.pending(), [])
        store.register(phone['id'], 'fcm', 'new-' + TOKEN)
        self.assertEqual(len(store.pending()), 1)
        self.assertIsNone(store.overview()['phones'][0]['last_error'])

    def test_other_errors_keep_the_registration_and_a_rotated_token_survives(self):
        store, phone = self.registered()
        for code in ('INVALID_ARGUMENT', 'SENDER_ID_MISMATCH', 'OAUTH_INVALID_GRANT', 'UNAVAILABLE'):
            self.fail_with(store, code)
            self.now[0] += 4000
            self.assertTrue(store.status(phone['id'])['registered'], code)
        self.assertEqual(store.overview()['phones'][0]['last_error']['code'], 'UNAVAILABLE')
        row = store.pending()[0]
        store.register(phone['id'], 'fcm', 'rotated-' + TOKEN)
        store.outcome(row['id'], False, FcmError('UNREGISTERED'), row['token'])
        self.assertTrue(store.status(phone['id'])['registered'])

    def test_non_provider_exceptions_record_only_the_class_name(self):
        store, phone = self.registered()
        def provider(row):
            raise RuntimeError('Bearer ' + TOKEN)
        with self.assertLogs(level='WARNING') as logs:
            MobilePushPump(store, provider).tick()
        self.assertEqual(store.overview()['phones'][0]['last_error']['code'], 'RuntimeError')
        self.assertNotIn(TOKEN, ''.join(logs.output))
        self.assertIn('RuntimeError', logs.output[0])

    def test_an_accepted_hint_clears_the_error_but_keeps_the_time_of_the_last_success(self):
        store, phone = self.registered()
        self.fail_with(store, 'UNAVAILABLE')
        self.assertEqual(store.overview()['phones'][0]['last_error']['code'], 'UNAVAILABLE')
        self.now[0] += 4000
        MobilePushPump(store, lambda row: None).tick()
        overview = store.overview()
        self.assertIsNone(overview['phones'][0]['last_error'])
        self.assertIsNone(overview['last_error'])
        self.assertEqual(overview['phones'][0]['last_ok'], self.now[0])

    def test_success_records_the_last_ok_time(self):
        store, phone = self.registered()
        MobilePushPump(store, lambda row: None).tick()
        health = store.overview()['phones'][0]
        self.assertEqual(health['last_accepted'], self.now[0])
        self.assertIsNone(health['last_error'])
        self.assertEqual(health['last_ok'], self.now[0])


class StatusTests(Fixture):
    def test_status_reports_facts_without_content_tokens_or_names(self):
        app = self.app(self.config(delivery_mode='native'))
        client = TestClient(app)
        phone = self.phone(app)
        stale = self.phone(app, token=None)
        revoked = self.phone(app, token='other-' + TOKEN)
        app.state.mobile_events.devices.revoke(revoked['id'])
        self.submit(client)
        app.state.notification_pump.tick()
        app.state.native_push_pump.tick()
        self.now[0] += 120
        text = client.get('/v1/notifications/status', headers={'Authorization': 'Bearer ' + OWNER}).text
        for private in ('Sentinel request text', TOKEN, phone['token'], 'Phone', revoked['id']):
            self.assertNotIn(private, text)
        status = json.loads(text)
        self.assertEqual((status['mode'], status['fcm_configured'], status['unreceived']), ('native', True, 2))
        self.assertEqual(status['oldest_unreceived_age'], 120)
        self.assertEqual(status['last_accepted'], self.now[0] - 120)
        self.assertIsNone(status['last_receipt'])
        self.assertIsNone(status['last_error'])
        by_id = {item['id']: item for item in status['phones']}
        self.assertEqual(set(by_id), {phone['id'], stale['id']})
        self.assertTrue(by_id[phone['id']]['registered'])
        self.assertFalse(by_id[stale['id']]['registered'])
        self.assertEqual(set(by_id[phone['id']]), {'id', 'created', 'seen', 'registered', 'registered_at', 'last_ok', 'last_accepted',
                                                   'last_receipt', 'unreceived', 'oldest_unreceived_age', 'last_error'})

    def test_expired_events_are_not_counted_as_unreceived(self):
        store = self.store()
        store.devices.exchange(store.devices.pairing()['code'], 'Phone')
        store.enqueue({'type': 'task', 'message': 'Short lived'}, ttl=60)
        self.assertEqual(store.overview()['unreceived'], 1)
        self.now[0] += 3600
        overview = store.overview()
        self.assertEqual((overview['unreceived'], overview['oldest_unreceived_age']), (0, None))
        self.assertEqual((overview['phones'][0]['unreceived'], overview['phones'][0]['oldest_unreceived_age']), (0, None))

    def test_totals_take_the_oldest_age_and_the_latest_error_across_phones(self):
        store = self.store()
        phones = []
        for name in ('One', 'Two'):
            phones.append(store.devices.exchange(store.devices.pairing()['code'], name))
            self.now[0] += 1
        store.enqueue({'type': 'task', 'tag': 'a', 'message': 'First'}, phone=phones[0]['id'])
        self.now[0] += 100
        store.enqueue({'type': 'task', 'tag': 'b', 'message': 'Second'}, phone=phones[1]['id'])
        first, second = (store.events(phone['id'])['items'][0]['id'] for phone in phones)
        store.outcome(first, False, FcmError('UNAVAILABLE'))
        self.now[0] += 50
        store.outcome(second, False, FcmError('QUOTA_EXCEEDED'))
        overview = store.overview()
        self.assertEqual([phone['oldest_unreceived_age'] for phone in overview['phones']], [150, 50])
        self.assertEqual((overview['unreceived'], overview['oldest_unreceived_age']), (2, 150))
        self.assertEqual(overview['last_error'], {'code': 'QUOTA_EXCEEDED', 'at': self.now[0]})

    def test_totals_take_the_latest_accepted_hint_and_receipt_across_phones(self):
        store = self.store()
        phones, accepted, received = [], [], []
        for name in ('One', 'Two'):
            phones.append(store.devices.exchange(store.devices.pairing()['code'], name))
            store.enqueue({'type': 'task', 'tag': name, 'message': 'Update'}, phone=phones[-1]['id'])
            store.outcome(store.events(phones[-1]['id'])['items'][0]['id'], True)
            accepted.append(self.now[0])
            self.now[0] += 100
        for phone in phones:
            store.receipt(phone['id'], store.events(phone['id'])['items'][0]['sequence'])
            received.append(self.now[0])
            self.now[0] += 10
        overview = store.overview()
        self.assertEqual((overview['last_accepted'], overview['last_receipt']), (accepted[1], received[1]))
        self.assertLess(accepted[0], accepted[1])
        self.assertLess(received[0], received[1])

    def test_receipt_clears_the_unreceived_count_and_errors_are_reported(self):
        app = self.app(self.config(delivery_mode='native'))
        client = TestClient(app)
        phone = self.phone(app)
        self.submit(client)
        app.state.notification_pump.tick()
        with self.assertLogs(level='WARNING'):
            MobilePushPump(app.state.mobile_events, lambda row: (_ for _ in ()).throw(FcmError('SENDER_ID_MISMATCH'))).tick()
        status = client.get('/v1/notifications/status', headers={'Authorization': 'Bearer ' + OWNER}).json()
        self.assertEqual(status['last_error'], {'code': 'SENDER_ID_MISMATCH', 'at': self.now[0]})
        app.state.mobile_events.receipt(phone['id'], self.events(app, phone)[0]['sequence'])
        status = client.get('/v1/notifications/status', headers={'Authorization': 'Bearer ' + OWNER}).json()
        self.assertEqual((status['unreceived'], status['oldest_unreceived_age'], status['last_receipt']), (0, None, self.now[0]))


class PreflightTests(Fixture):
    def run_check(self, notifications, paired=True):
        lines = []
        return check(notifications, paired, lines.append), lines

    def fake(self, token=None, dry=None):
        def request(url, body, headers):
            if url.endswith('/token'):
                if token:
                    raise token
                return {'access_token': 'mock-access', 'expires_in': 3600}
            if dry:
                raise dry
            return {'name': 'projects/demo-project/messages/dry-run'}
        return self.provider(request)

    def test_valid_configuration_and_credential_pass(self):
        ok, lines = self.run_check({**self.config(delivery_mode='native'), 'native_provider': self.fake()})
        self.assertTrue(ok, lines)
        self.assertEqual([line[:4] for line in lines], ['ok  '] * 3)

    def test_dry_run_sends_validate_only_to_a_topic_never_a_phone(self):
        bodies = []
        provider = self.provider(lambda url, body, headers: {'access_token': 'a', 'expires_in': 9} if url.endswith('/token') else bodies.append(json.loads(body)) or {})
        provider.dry_run()
        self.assertTrue(bodies[0]['validate_only'])
        self.assertNotIn('token', bodies[0]['message'])

    def test_configuration_errors_fail_with_a_readable_reason(self):
        for notifications, reason in (({**self.config(delivery_mode='native '), 'native_provider': None}, 'delivery is retired'),
                                      ({**self.config(delivery_mode='native'), 'native_provider': None}, 'companion_push credentials'),
                                      ({'enabled': True, 'public_url': 'https://assistant.example.test'}, 'companion_push credentials'),
                                      ({**self.config(), 'public_url': 'http://assistant.example.test'}, 'public HTTPS origin')):
            ok, lines = self.run_check(notifications)
            self.assertFalse(ok)
            self.assertIn(reason, lines[0])
        ok, lines = self.run_check(self.config(delivery_mode='native'), paired=False)
        self.assertIn('require Companion pairing', lines[0])
        ok, lines = self.run_check({'enabled': True, 'public_url': 'https://assistant.example.test', 'companion_push': {
            'project_id': 'demo-project', 'service_account_file': str(self.root/'absent.json')}})
        self.assertFalse(ok)
        self.assertIn('FileNotFoundError', lines[0])

    def test_oauth_failure_blocks_the_deploy_and_skips_the_dry_run(self):
        ok, lines = self.run_check({**self.config(), 'native_provider': self.fake(token=http_error(400, {'error': 'invalid_grant'}))})
        self.assertFalse(ok)
        self.assertEqual(lines[-1], 'FAIL firebase oauth token exchange: OAUTH_INVALID_GRANT')
        self.assertEqual(len(lines), 2)

    def test_a_google_outage_only_warns_in_every_mode_and_skips_the_dry_run(self):
        for mode in ('native',):
            for failure, code in ((urllib.error.URLError('network down'), 'OAUTH_UNREACHABLE'), (http_error(503), 'OAUTH_UNAVAILABLE'),
                                  (http_error(429), 'OAUTH_QUOTA_EXCEEDED')):
                ok, lines = self.run_check({**self.config(delivery_mode=mode), 'native_provider': self.fake(token=failure)})
                self.assertTrue(ok, (mode, code))
                self.assertEqual(lines[-1], 'warn firebase oauth token exchange inconclusive: ' + code)
                self.assertEqual(len(lines), 2)

    def test_credential_rejections_from_the_token_endpoint_still_block(self):
        for failure, code in ((http_error(400, {'error': 'invalid_client'}), 'OAUTH_INVALID_CLIENT'),
                              (http_error(400, {'error': 'unauthorized_client'}), 'OAUTH_UNAUTHORIZED_CLIENT'),
                              (http_error(401), 'OAUTH_UNAUTHENTICATED')):
            ok, lines = self.run_check({**self.config(), 'native_provider': self.fake(token=failure)})
            self.assertFalse(ok, code)
            self.assertEqual(lines[-1], 'FAIL firebase oauth token exchange: ' + code)

        def bad_key(body):
            raise ValueError('unparseable key')
        ok, lines = self.run_check({**self.config(), 'native_provider': self.provider(lambda *args: {}, signer=bad_key)})
        self.assertFalse(ok)
        self.assertEqual(lines[-1], 'FAIL firebase oauth token exchange: OAUTH_CREDENTIAL')

    def test_dry_run_rejection_blocks_only_for_credential_project_or_permission(self):
        for failure, code in ((http_error(401, fcm_body(None, 'UNAUTHENTICATED')), 'UNAUTHENTICATED'),
                              (http_error(403, fcm_body(None, 'PERMISSION_DENIED')), 'PERMISSION_DENIED'),
                              (http_error(404, fcm_body(None, 'NOT_FOUND')), 'NOT_FOUND'),
                              (http_error(401, fcm_body('THIRD_PARTY_AUTH_ERROR')), 'THIRD_PARTY_AUTH_ERROR')):
            ok, lines = self.run_check({**self.config(), 'native_provider': self.fake(dry=failure)})
            self.assertFalse(ok, code)
            self.assertEqual(lines[-1], 'FAIL firebase send dry run: ' + code)
        ok, lines = self.run_check({**self.config(), 'native_provider': self.fake(dry=http_error(400, fcm_body('INVALID_ARGUMENT')))})
        self.assertTrue(ok)
        self.assertEqual(lines[-1], 'warn firebase send dry run inconclusive: INVALID_ARGUMENT')

    def test_native_mode_needs_no_home_assistant_settings(self):
        ok, lines = self.run_check({'enabled': True, 'public_url': 'https://assistant.example.test', 'delivery_mode': 'native',
                                    'native_provider': self.fake()})
        self.assertTrue(ok, lines)
        self.assertEqual(lines[0], 'ok   config: delivery mode native')

    def test_main_treats_the_groceries_token_file_as_companion_pairing(self):
        lines = []
        environ = {'ASSISTANT_NOTIFICATIONS_CONFIG': str(self.root/'notifications.json'), 'ASSISTANT_GROCERIES_TOKEN_FILE': '/data/groceries-token'}
        (self.root/'notifications.json').write_text(json.dumps({'enabled': True, 'delivery_mode': 'native', 'public_url': 'https://assistant.example.test'}))
        self.assertEqual(preflight(environ, lines.append), 1)
        self.assertIn('companion_push credentials', lines[-1])
        self.assertNotIn('pairing', lines[-1])

    def test_main_reads_the_notifications_file_and_reports_an_exit_status(self):
        lines = []
        environ = {'ASSISTANT_NOTIFICATIONS_CONFIG': str(self.root/'notifications.json')}
        self.assertEqual(preflight(environ, lines.append), 0)
        self.assertIn('disabled', lines[-1])
        (self.root/'notifications.json').write_text('{"enabled": false, "delivery_mode": "bogus"}')
        self.assertEqual(preflight(environ, lines.append), 0)
        (self.root/'notifications.json').write_text('{not json')
        self.assertEqual(preflight(environ, lines.append), 1)
        (self.root/'notifications.json').write_text('[]')
        self.assertEqual(preflight(environ, lines.append), 1)
        (self.root/'notifications.json').write_text(json.dumps({'enabled': True, 'delivery_mode': 'native', 'public_url': 'https://assistant.example.test'}))
        self.assertEqual(preflight(environ, lines.append), 1)
        self.assertIn('require Companion pairing', lines[-1])
        (self.root/'notifications.json').write_text(json.dumps({'enabled': True, 'public_url': 'https://assistant.example.test',
}))
        self.assertEqual(preflight(environ, lines.append), 1)
        self.assertIn('Companion pairing', lines[-1])

    def test_deploy_script_runs_the_preflight_before_replacing_the_relay(self):
        script = (Path(__file__).resolve().parents[1]/'scripts/deploy_server.sh').read_text()
        gate = next(line for line in script.splitlines() if 'personal_assistant.relay.preflight' in line)
        self.assertIn('run --rm --no-deps -T', gate)
        self.assertNotIn('||', gate)
        self.assertIn('set -eu', script)
        self.assertLess(script.index(gate), script.index('up -d'))
        self.assertLess(script.index('build relay'), script.index(gate))


if __name__ == '__main__':
    unittest.main()
