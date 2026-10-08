import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from personal_assistant.relay.api import create_app
from personal_assistant.relay.store import Conflict, Queue


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'queue.sqlite3'
        self.now = 1900000000.0
        self.clock = lambda: self.now
        self.queue = Queue(self.path, self.clock)
        self.submit = 's' * 64
        self.worker = 'w' * 64
        self.client = TestClient(create_app(self.path, self.submit, self.worker, self.clock))
        self.headers = {'Authorization': 'Bearer ' + self.submit}
        self.worker_headers = {'Authorization': 'Bearer ' + self.worker}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def payload(self, name='request-123'):
        return {'id': name, 'command': 'Check my calendar', 'timezone': 'Europe/Berlin',
                'created_at': None, 'expires_at': None}

    def test_persistence_and_duplicate_upload(self):
        payload = self.payload()
        first = self.client.post('/v1/commands', json=payload, headers=self.headers)
        self.assertEqual(first.status_code, 201)
        self.now += 1
        repeated = self.client.post('/v1/commands', json=payload, headers=self.headers)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(first.json()['job']['created'], repeated.json()['job']['created'])
        restored = Queue(self.path, self.clock)
        self.assertEqual(restored.get(payload['id'])['state'], 'queued')
        self.assertEqual(len(restored.history(payload['id'])), 1)
        changed = {**payload, 'command': 'Another command'}
        self.assertEqual(self.client.post('/v1/commands', json=changed, headers=self.headers).status_code, 409)

    def test_concurrent_uploads_and_claims_are_serialized(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.queue.submit(self.payload()), range(12)))
        self.assertEqual(sum(created for _, created in results), 1)
        self.queue.heartbeat('ready')
        with ThreadPoolExecutor(max_workers=6) as pool:
            claims = list(pool.map(lambda _: self.queue.claim(), range(6)))
        self.assertEqual(sum(job is not None for job in claims), 1)

    def test_late_upload_retry_returns_original_expired_record(self):
        payload = self.payload()
        payload['expires_at'] = datetime.fromtimestamp(self.now + 30, timezone.utc).isoformat()
        original, created = self.queue.submit(payload)
        self.assertTrue(created)
        self.now += 31
        retried, created = self.queue.submit(payload)
        self.assertFalse(created)
        self.assertEqual(retried['state'], 'expired')
        self.assertEqual(retried['created'], original['created'])
        self.assertEqual([r['kind'] for r in self.queue.history(payload['id'])], ['submitted', 'expired'])

    def test_stale_lease_fenced_and_new_worker_can_complete(self):
        self.queue.submit(self.payload())
        self.queue.heartbeat('ready')
        old = self.queue.claim(15)
        self.now += 16
        new = self.queue.claim(60)
        self.assertEqual(new['attempts'], 2)
        self.assertNotEqual(old['lease_token'], new['lease_token'])
        with self.assertRaises(Conflict):
            self.queue.finish(old['id'], old['lease_token'], 'completed', {})
        with self.assertRaises(Conflict):
            self.queue.renew(old['id'], old['lease_token'])
        result = {'summary': 'Calendar checked', 'trace_ref': 'runs/example.jsonl'}
        self.queue.finish(new['id'], new['lease_token'], 'completed', result)
        self.queue.finish(new['id'], new['lease_token'], 'completed', result)
        self.assertEqual(self.queue.get(new['id'])['result'], result)
        self.assertEqual([r['kind'] for r in self.queue.history(new['id'])].count('completed'), 1)

    def test_deadline_expiry_blocks_running_and_queued_commands(self):
        for name in ('queued-123', 'running-123'):
            payload = self.payload(name)
            payload['expires_at'] = datetime.fromtimestamp(self.now + 30, timezone.utc).isoformat()
            self.queue.submit(payload)
        self.queue.heartbeat('ready')
        claimed = self.queue.claim()
        self.now += 31
        with self.assertRaises(Conflict):
            self.queue.finish(claimed['id'], claimed['lease_token'], 'completed', {})
        self.assertEqual(self.queue.get('queued-123')['state'], 'expired')
        self.assertEqual(self.queue.get('running-123')['state'], 'expired')
        self.assertIsNone(self.queue.claim())

    def test_cancelled_running_command_rejects_acknowledgement(self):
        self.queue.submit(self.payload())
        self.queue.heartbeat('ready')
        job = self.queue.claim()
        self.queue.cancel(job['id'])
        self.queue.cancel(job['id'])
        with self.assertRaises(Conflict):
            self.queue.finish(job['id'], job['lease_token'], 'completed', {})
        self.assertIsNone(self.queue.claim())

    def test_renewal_and_readiness_expiry(self):
        self.queue.submit(self.payload())
        self.assertIsNone(self.queue.claim())
        self.queue.heartbeat('blocked')
        self.assertEqual(self.queue.status()['laptop'], 'blocked')
        self.assertIsNone(self.queue.claim())
        self.queue.heartbeat('ready')
        job = self.queue.claim(15)
        self.now += 10
        self.queue.renew(job['id'], job['lease_token'], 60)
        self.now += 6
        self.queue.finish(job['id'], job['lease_token'], 'needs_input', {'question': 'Which date?'})
        self.now += 44
        self.assertEqual(self.queue.status()['laptop'], 'unavailable')

    def test_role_authentication_and_no_lease_leak(self):
        self.assertEqual(self.client.get('/healthz').status_code, 200)
        self.assertEqual(self.client.get('/v1/status').status_code, 401)
        self.assertEqual(self.client.post('/v1/commands', json=self.payload(), headers=self.worker_headers).status_code, 401)
        self.assertEqual(self.client.post('/v1/worker/heartbeat', json={'readiness': 'ready'}, headers=self.headers).status_code, 401)
        self.client.post('/v1/commands', json=self.payload(), headers=self.headers)
        self.client.post('/v1/worker/heartbeat', json={'readiness': 'ready'}, headers=self.worker_headers)
        claim = self.client.post('/v1/worker/claim', json={}, headers=self.worker_headers).json()['job']
        self.assertIn('lease_token', claim)
        public = self.client.get('/v1/commands/request-123', headers=self.headers).json()
        self.assertNotIn('lease_token', public)
        self.assertEqual(self.client.get('/docs').status_code, 404)

    def test_validation_and_streamed_body_limit(self):
        for changed in ({'timezone': 'Invalid/Zone'}, {'command': '   '},
                        {'created_at': '2030-01-01T10:00'}, {'id': '../bad'},
                        {'extra': 'unexpected'}):
            result = self.client.post('/v1/commands', json={**self.payload(), **changed}, headers=self.headers)
            self.assertEqual(result.status_code, 422)
        oversized = self.client.post('/v1/commands', content=iter([b'x' * 9000, b'x' * 9000]),
                                     headers={**self.headers, 'Content-Type': 'application/json'})
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(self.queue.status()['queued'], 0)


if __name__ == '__main__':
    unittest.main()
