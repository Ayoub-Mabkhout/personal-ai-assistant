import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from personal_assistant.relay.api import create_app
from personal_assistant.relay.file_drops import settings_from_environment
from personal_assistant.worker.runtime import TransportError
from personal_assistant.worker.send_file import UploadRejected, default_id, send

OWNER, WORKER = 'o' * 40, 'w' * 40
MIB = 1024 * 1024


def manifest(content, name='March invoice.pdf', **extra):
    value = {'name': name, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
             'mime': 'application/pdf', **extra}
    return {'X-File-Manifest': base64.b64encode(json.dumps(value).encode()).decode()}


class Relay:
    def __init__(self, directory, now, **limits):
        path = Path(directory)
        self.app = create_app(path / 'queue.sqlite3', OWNER, WORKER, clock=lambda: now[0],
                              groceries={'path': path / 'groceries.sqlite3', 'internal_token': 'g' * 40,
                                         'ha_url': 'http://homeassistant:8123', 'assets': path},
                              file_drops=limits or None)
        self.client = TestClient(self.app)
        self.devices = self.app.state.mobile_events.devices
        self.drops = self.app.state.file_drops
        self.store = path / 'file-drops'

    def pair(self):
        phone = self.devices.exchange(self.devices.pairing()['code'], 'Phone')
        return phone['id'], {'Authorization': 'Bearer ' + phone['token']}

    def put(self, identifier, content, auth=WORKER, **extra):
        return self.client.put('/v1/files/' + identifier, content=content,
                               headers={'Authorization': 'Bearer ' + auth, **manifest(content, **extra)})


class FakeClient:
    """send_file transport over the in-process relay."""
    def __init__(self, relay, token=WORKER):
        self.client, self.headers, self.uploads = relay.client, {'Authorization': 'Bearer ' + token}, 0

    def call(self, path, payload=None):
        response = self.client.get(path, headers=self.headers)
        if response.status_code >= 300:
            raise TransportError(response.status_code)
        return response.json()

    def upload(self, path, source, size, headers):
        self.uploads += 1
        response = self.client.put(path, content=source.read(), headers={**headers, **self.headers})
        if response.status_code >= 300:
            raise UploadRejected(response.status_code, response.json()['detail'])
        return response.json()


class FileDropTests(unittest.TestCase):
    def test_upload_event_download_receipt_deletes_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            now = [1000.0]
            relay = Relay(d, now)
            phone, paired = relay.pair()
            content = b'%PDF-1.7 invoice' * 1000
            created = relay.put('march-invoice-01', content, note='From the invoices folder')
            self.assertEqual(created.status_code, 200, created.text)
            body = created.json()
            self.assertEqual((body['state'], body['phone'], body['created_now']), ('ready', phone, True))
            self.assertTrue((relay.store / 'march-invoice-01').is_file())
            # The FCM-hinted event carries metadata only, never the bytes.
            events = relay.client.get('/groceries/v1/mobile/events', headers=paired).json()['items']
            self.assertEqual(len(events), 1)
            event = events[0]['payload']
            self.assertEqual((event['type'], event['file_id'], event['title'], event['message']),
                             ('file', 'march-invoice-01', 'File ready: March invoice.pdf', 'From the invoices folder'))
            self.assertEqual(event['sha256'], hashlib.sha256(content).hexdigest())
            listed = relay.client.get('/groceries/v1/mobile/files', headers=paired).json()['items']
            self.assertEqual([item['id'] for item in listed], ['march-invoice-01'])
            download = relay.client.get('/groceries/v1/mobile/files/march-invoice-01', headers=paired)
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.content, content)
            self.assertEqual(download.headers['x-file-sha256'], hashlib.sha256(content).hexdigest())
            self.assertEqual(download.headers['cache-control'], 'no-store')
            wrong = relay.client.post('/groceries/v1/mobile/files/march-invoice-01/receipt', headers=paired, json={'sha256': '0' * 64})
            self.assertEqual(wrong.status_code, 409)
            self.assertTrue((relay.store / 'march-invoice-01').is_file())
            receipt = {'sha256': hashlib.sha256(content).hexdigest()}
            for _ in range(2):
                done = relay.client.post('/groceries/v1/mobile/files/march-invoice-01/receipt', headers=paired, json=receipt)
                self.assertEqual(done.json(), {'id': 'march-invoice-01', 'state': 'delivered'})
            self.assertFalse((relay.store / 'march-invoice-01').exists())
            self.assertEqual(relay.client.get('/groceries/v1/mobile/files', headers=paired).json()['items'], [])
            self.assertEqual(relay.client.get('/groceries/v1/mobile/files/march-invoice-01', headers=paired).status_code, 410)
            # A retried upload of a delivered drop reports it and sends nothing new to the phone.
            again = relay.put('march-invoice-01', content, note='From the invoices folder').json()
            self.assertEqual((again['state'], again['created_now']), ('delivered', False))
            self.assertEqual(len(relay.client.get('/groceries/v1/mobile/events', headers=paired).json()['items']), 1)

    def test_retry_is_idempotent_and_a_different_file_under_the_id_conflicts(self):
        with tempfile.TemporaryDirectory() as d:
            relay = Relay(d, [1000.0])
            _, paired = relay.pair()
            content = b'slides'
            first = relay.put('thesis-slides-1', content, name='slides.pptx')
            second = relay.put('thesis-slides-1', content, name='slides.pptx', auth=OWNER)
            self.assertTrue(first.json()['created_now'])
            self.assertFalse(second.json()['created_now'])
            self.assertEqual(len(relay.client.get('/groceries/v1/mobile/events', headers=paired).json()['items']), 1)
            self.assertEqual(relay.put('thesis-slides-1', b'other', name='slides.pptx').status_code, 409)
            self.assertEqual(relay.put('thesis-slides-1', content, name='renamed.pptx').status_code, 409)
            self.assertEqual(sorted(p.name for p in relay.store.iterdir()), ['thesis-slides-1'])

    def test_authentication_is_separated_between_owner_and_phone(self):
        with tempfile.TemporaryDirectory() as d:
            relay = Relay(d, [1000.0])
            phone, paired = relay.pair()
            content = b'private'
            self.assertEqual(relay.put('owner-only-file', content, auth='x' * 40).status_code, 401)
            self.assertEqual(relay.client.put('/v1/files/owner-only-file', content=content, headers={
                **paired, **manifest(content)}).status_code, 401)
            self.assertEqual(relay.client.get('/v1/files/phones', headers=paired).status_code, 401)
            self.assertEqual(relay.put('owner-only-file', content).status_code, 200)
            # Owner credentials cannot use the phone mount, and another phone cannot fetch or confirm it.
            owner = {'Authorization': 'Bearer ' + OWNER}
            self.assertEqual(relay.client.get('/groceries/v1/mobile/files/owner-only-file', headers=owner).status_code, 401)
            _, other = relay.pair()
            self.assertEqual(relay.client.get('/groceries/v1/mobile/files/owner-only-file', headers=other).status_code, 404)
            self.assertEqual(relay.client.post('/groceries/v1/mobile/files/owner-only-file/receipt', headers=other,
                                               json={'sha256': hashlib.sha256(content).hexdigest()}).status_code, 404)
            self.assertEqual(relay.client.get('/groceries/v1/mobile/files', headers=other).json()['items'], [])
            self.assertEqual(relay.client.get('/groceries/v1/mobile/files/owner-only-file', headers=paired).content, content)
            # Two phones are now paired: the sender has to choose one.
            self.assertEqual(relay.put('ambiguous-phone', content).status_code, 409)
            chosen = relay.put('chosen-phone-01', content, phone=phone).json()
            self.assertEqual(chosen['phone'], phone)

    def test_size_limit_checksum_names_and_quota(self):
        with tempfile.TemporaryDirectory() as d:
            relay = Relay(d, [1000.0], max_bytes=1024, quota=2048)
            relay.pair()
            self.assertEqual(relay.put('too-large-file', b'x' * 1025).status_code, 413)
            lying = relay.client.put('/v1/files/lying-upload', content=b'abcd', headers={
                'Authorization': 'Bearer ' + WORKER, **manifest(b'abce')})
            self.assertEqual(lying.status_code, 400)
            for bad in ('../secret.txt', 'C:\\x.pdf', '..', '', 'a\x00b'):
                self.assertEqual(relay.put('bad-file-name', b'x', name=bad).status_code, 400, bad)
            self.assertEqual(relay.put('first-quota', b'x' * 1024).status_code, 200)
            self.assertEqual(relay.put('second-quota', b'y' * 1024).status_code, 200)
            self.assertEqual(relay.put('third-quota', b'z' * 10).status_code, 507)
            self.assertEqual(sorted(p.name for p in relay.store.iterdir()), ['first-quota', 'second-quota'])
            self.assertEqual(relay.client.put('/v1/files/no-phone-file', content=b'x',
                                              headers={'Authorization': 'Bearer ' + WORKER}).status_code, 400)

    def test_expiry_cancel_and_revoked_phone_delete_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            now = [1000.0]
            relay = Relay(d, now, ttl=3600)
            phone, paired = relay.pair()
            relay.put('expiring-file', b'old')
            relay.put('cancelled-file', b'cancel')
            owner = {'Authorization': 'Bearer ' + OWNER}
            self.assertEqual(relay.client.post('/v1/files/cancelled-file/cancel', headers=owner).json()['state'], 'cancelled')
            self.assertFalse((relay.store / 'cancelled-file').exists())
            now[0] += 3601
            self.assertEqual(relay.client.get('/groceries/v1/mobile/files/expiring-file', headers=paired).status_code, 410)
            self.assertEqual(relay.client.get('/v1/files/expiring-file', headers=owner).json()['state'], 'expired')
            self.assertFalse((relay.store / 'expiring-file').exists())
            relay.put('revoked-phone-file', b'new')
            relay.devices.revoke(phone)
            self.assertEqual(relay.client.get('/v1/files/revoked-phone-file', headers=owner).json()['state'], 'expired')
            self.assertEqual(list(relay.store.iterdir()), [])
            # Terminal records are forgotten after their retention period.
            now[0] += 31 * 86400
            self.assertEqual(relay.client.get('/v1/files/expiring-file', headers=owner).status_code, 404)

    def test_sender_selects_phone_reuses_its_id_and_reports_limits(self):
        with tempfile.TemporaryDirectory() as d:
            relay = Relay(d, [1000.0], max_bytes=MIB)
            fake = FakeClient(relay)
            path = Path(d) / 'Report  final.pdf'
            path.write_bytes(b'report body')
            with self.assertRaisesRegex(ValueError, 'pair Assistant Companion'):
                send(fake, path)
            phone, paired = relay.pair()
            first = send(fake, path, note='Q3 numbers')
            self.assertEqual((first['name'], first['mime'], first['phone']), ('Report final.pdf', 'application/pdf', phone))
            self.assertEqual(first['id'], default_id('Report final.pdf', hashlib.sha256(b'report body').hexdigest(), 'Q3 numbers'))
            second = send(fake, path, note='Q3 numbers')
            self.assertEqual((second['id'], second['created_now'], fake.uploads), (first['id'], False, 1))
            self.assertEqual(len(relay.client.get('/groceries/v1/mobile/events', headers=paired).json()['items']), 1)
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'different file'):
                send(fake, path, request_id=first['id'])
            big = Path(d) / 'big.bin'
            big.write_bytes(b'x' * (MIB + 1))
            with self.assertRaisesRegex(ValueError, 'transfer limit is 1 MiB'):
                send(fake, big)
            relay.pair()
            with self.assertRaisesRegex(ValueError, 'More than one phone'):
                send(fake, path)
            self.assertEqual(send(fake, path, phone=phone)['phone'], phone)

    def test_environment_settings(self):
        self.assertEqual(settings_from_environment({}), {'max_bytes': 50 * MIB, 'ttl': 7 * 86400, 'quota': 1024 * MIB})
        self.assertEqual(settings_from_environment({'ASSISTANT_FILE_DROP_MAX_MIB': '10', 'ASSISTANT_FILE_DROP_TTL_DAYS': '1'})['ttl'], 86400)
        with self.assertRaises(ValueError):
            settings_from_environment({'ASSISTANT_FILE_DROP_MAX_MIB': 'many'})


if __name__ == '__main__':
    unittest.main()
