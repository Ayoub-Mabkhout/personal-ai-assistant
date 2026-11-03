import json
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from personal_assistant.relay import wakeups
from personal_assistant.relay.api import create_app
from personal_assistant.relay.client import long_poll_seconds
from personal_assistant.relay.store import Queue
from personal_assistant.worker.runtime import Worker

SUBMIT = 'synthetic-submit-' * 3
WORKER = 'synthetic-worker-' * 3
OWNER = {'Authorization': 'Bearer ' + SUBMIT}
LAPTOP = {'Authorization': 'Bearer ' + WORKER}
TRAIN = '/train/api'


def later(seconds, action):
    timer = threading.Timer(seconds, action)
    timer.start()
    return timer


class RelayLongPollTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        (root/'web').mkdir()
        (root/'web'/'index.html').write_text('<title>Train fixture</title>', encoding='utf-8')
        self.app = create_app(root/'queue.sqlite3', SUBMIT, WORKER, train_assets=root/'web')
        self.client = TestClient(self.app, base_url='https://train.test')
        self.addCleanup(self.client.close)

    def submit(self, identifier, path='/v1/commands', key='command'):
        response = self.client.post(path, headers=OWNER, json={'id': identifier, key: 'Show my calendar',
                                                             **({'timezone': 'Europe/Berlin'} if key == 'command' else {})})
        self.assertIn(response.status_code, (200, 201), response.text)

    def test_waiting_claim_returns_as_soon_as_a_job_is_queued(self):
        for prefix, path, key in [('', '/v1/commands', 'command'), ('/agent', '/v1/agent/prompts', 'prompt')]:
            with self.subTest(queue=prefix or 'command'):
                self.client.post('/v1'+prefix+'/worker/heartbeat', headers=LAPTOP, json={'readiness': 'ready'})
                timer = later(0.4, lambda: self.submit('long-poll'+prefix.replace('/', '-')+'-job', path, key))
                started = time.monotonic()
                response = self.client.post('/v1'+prefix+'/worker/claim?wait=20', headers=LAPTOP, json={'lease_seconds': 60})
                elapsed = time.monotonic() - started
                timer.join()
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['job']['id'], 'long-poll'+prefix.replace('/', '-')+'-job')
                self.assertEqual(response.json()['wait_seconds'], 20)
                self.assertGreaterEqual(elapsed, 0.3)
                self.assertLess(elapsed, 5)

    def test_waiting_claim_returns_empty_after_timeout_and_old_clients_do_not_wait(self):
        self.client.post('/v1/worker/heartbeat', headers=LAPTOP, json={'readiness': 'ready'})
        started = time.monotonic()
        response = self.client.post('/v1/worker/claim?wait=1', headers=LAPTOP, json={'lease_seconds': 60}).json()
        self.assertGreaterEqual(time.monotonic() - started, 0.9)
        self.assertEqual(response, {'job': None, 'wait_seconds': 1})
        started = time.monotonic()
        legacy = self.client.post('/v1/worker/claim', headers=LAPTOP, json={'lease_seconds': 60}).json()
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(legacy, {'job': None, 'wait_seconds': 0})
        self.assertEqual(self.client.post('/v1/worker/claim?wait=-1', headers=LAPTOP, json={}).status_code, 422)
        self.assertEqual(wakeups.requested_wait(600), wakeups.MAX_WAIT_SECONDS)

    def test_full_waiter_budget_answers_immediately_without_waiting(self):
        self.client.post('/v1/worker/heartbeat', headers=LAPTOP, json={'readiness': 'ready'})
        with patch.object(wakeups.budget, 'limit', 0):
            started = time.monotonic()
            response = self.client.post('/v1/worker/claim?wait=20', headers=LAPTOP, json={'lease_seconds': 60}).json()
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(response, {'job': None, 'wait_seconds': 0})

    def test_worker_timings_are_recorded_with_the_result(self):
        self.client.post('/v1/worker/heartbeat', headers=LAPTOP, json={'readiness': 'ready'})
        self.submit('timed-command-job')
        job = self.client.post('/v1/worker/claim?wait=5', headers=LAPTOP, json={'lease_seconds': 60}).json()['job']
        finished = self.client.post('/v1/worker/timed-command-job/result', headers=LAPTOP, json={
            'lease_token': job['lease_token'], 'state': 'completed', 'result': {'summary': 'Done'},
            'timings': {'execution_started_after': 0.2, 'execution_finished_after': 1.5}})
        self.assertEqual(finished.status_code, 200, finished.text)
        history = self.client.get('/v1/commands/timed-command-job/history', headers=OWNER).json()
        kinds = [event['kind'] for event in history]
        self.assertEqual(kinds[:2], ['submitted', 'claimed'])
        self.assertIn('worker_timings', kinds)
        self.assertEqual(next(e for e in history if e['kind'] == 'worker_timings')['data']['execution_finished_after'], 1.5)

    def test_owner_and_member_coach_claims_wake_on_a_new_question(self):
        workouts = self.app.state.workouts
        workouts.heartbeat()
        timer = later(0.4, lambda: workouts.question('owner-wakes-coach', 'Plan my week'))
        started = time.monotonic()
        response = self.client.post('/v1/workout/trainer/claim?wait=20', headers=OWNER).json()
        timer.join()
        self.assertEqual(response['job']['id'], 'owner-wakes-coach')
        self.assertLess(time.monotonic() - started, 5)

        member = TestClient(self.app, base_url='https://train.test')
        self.addCleanup(member.close)
        user_id = member.post(TRAIN+'/join', json={'name': 'Synthetic Member'}).json()['id']
        other = workouts.for_user('someone-else')
        coach = f'/v1/train/users/{user_id}/workout/trainer'
        # Another athlete's question must not satisfy this member's waiting coach.
        later(0.2, lambda: other.question('not-for-this-coach', 'Unrelated'))
        timer = later(0.6, lambda: member.post(TRAIN+'/trainer/questions', json={'id': 'member-wakes-coach', 'text': 'Hello coach'}))
        started = time.monotonic()
        response = self.client.post(coach+'/claim?wait=20', headers=OWNER).json()
        timer.join()
        self.assertEqual(response['job']['id'], 'member-wakes-coach')
        self.assertLess(time.monotonic() - started, 5)
        empty = self.client.post(coach+'/claim?wait=1', headers=OWNER).json()
        self.assertEqual(empty, {'job': None, 'wait_seconds': 1})

        answer = self.client.put(coach+'/member-wakes-coach/answer', headers=OWNER, json={
            'token': response['job']['token'], 'text': 'Welcome.',
            'timings': {'model_started_after': 0.5, 'first_output_after': 2.0, 'first_text_after': 3.0, 'model_finished_after': 4.0}})
        self.assertEqual(answer.status_code, 200, answer.text)
        with workouts.db() as db:
            timings = json.loads(db.execute("SELECT timings FROM trainer WHERE id='member-wakes-coach'").fetchone()[0])
        self.assertEqual(timings['claims'], 1)
        self.assertAlmostEqual(timings['first_text'] - timings['claimed'], 3.0)
        self.assertTrue({'queued', 'claimed', 'model_started', 'first_output', 'model_finished', 'answered'} <= timings.keys())
        conversation = member.get(TRAIN+'/trainer/conversation').json()['items']
        self.assertNotIn('timings', conversation[0])

    def test_conversation_waits_for_a_visible_change(self):
        member = TestClient(self.app, base_url='https://train.test')
        self.addCleanup(member.close)
        user_id = member.post(TRAIN+'/join', json={'name': 'Synthetic Chatter'}).json()['id']
        first = member.get(TRAIN+'/trainer/conversation').json()
        self.assertEqual(first['wait_seconds'], 0)
        version = first['version']
        store = self.app.state.workouts.for_user(user_id)
        later(0.4, lambda: store.question('chat-change', 'Is this visible?'))
        started = time.monotonic()
        changed = member.get(TRAIN+'/trainer/conversation', params={'since': version, 'wait': 20}).json()
        self.assertLess(time.monotonic() - started, 5)
        self.assertNotEqual(changed['version'], version)
        self.assertEqual(changed['items'][-1]['id'], 'chat-change')
        started = time.monotonic()
        same = member.get(TRAIN+'/trainer/conversation', params={'since': changed['version'], 'wait': 1}).json()
        self.assertGreaterEqual(time.monotonic() - started, 0.9)
        self.assertEqual(same['version'], changed['version'])
        stale = member.get(TRAIN+'/trainer/conversation', params={'since': 'older-version', 'wait': 20}).json()
        self.assertEqual(stale['version'], changed['version'])


class WorkerLongPollTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.queue = Queue(self.root/'relay.sqlite3')

    def relay(self, long_poll):
        queue, calls = self.queue, []
        class Relay:
            def call(self, path, payload=None):
                calls.append(path)
                route = path.split('?')[0]
                if route.endswith('/heartbeat'): return queue.heartbeat(payload['readiness'])
                if route.endswith('/claim'):
                    return {'job': queue.claim(payload['lease_seconds']), **({'wait_seconds': 25} if long_poll else {})}
                if route.endswith('/result'):
                    calls.append(payload)
                    return queue.finish(route.split('/')[-2], payload['lease_token'], payload['state'], payload['result'], payload.get('timings'))
                if route.endswith('/renew'): return queue.renew(route.split('/')[-2], payload['lease_token'], payload['lease_seconds'])
                raise AssertionError(path)
        return Relay(), calls

    def worker(self, client):
        class Executor:
            capabilities = ['synthetic']
            def available(self): return True
            def execute(self, job, cancelled): return {'state': 'completed', 'result': {'summary': 'Done'}}
        return Worker({'runtime_dir': str(self.root/'worker')}, client, Executor())

    def test_worker_asks_for_long_poll_and_reports_phase_timings(self):
        client, calls = self.relay(long_poll=True)
        worker = self.worker(client)
        self.assertFalse(worker.tick())
        self.assertTrue(worker.long_poll)
        self.assertIn('/v1/worker/claim?wait=25', calls)
        self.queue.submit({'id': 'worker-long-poll', 'command': 'Synthetic', 'timezone': 'UTC'})
        self.assertTrue(worker.tick())
        result = next(c for c in calls if isinstance(c, dict))
        self.assertEqual(set(result['timings']), {'execution_started_after', 'execution_finished_after'})
        self.assertEqual(self.queue.get('worker-long-poll')['state'], 'completed')

    def test_worker_against_old_relay_sends_no_timings_and_keeps_its_interval(self):
        client, calls = self.relay(long_poll=False)
        worker = self.worker(client)
        self.assertFalse(worker.tick())
        self.assertFalse(worker.long_poll)
        self.queue.submit({'id': 'worker-old-relay', 'command': 'Synthetic', 'timezone': 'UTC'})
        self.assertTrue(worker.tick())
        self.assertNotIn('timings', next(c for c in calls if isinstance(c, dict)))

    def test_client_timeout_covers_the_requested_wait(self):
        self.assertEqual(long_poll_seconds('/v1/worker/claim?wait=25'), 25)
        self.assertEqual(long_poll_seconds('/v1/worker/claim'), 0)
        self.assertEqual(long_poll_seconds('/v1/worker/claim?wait=bad'), 0)


class CoachTimingTests(unittest.TestCase):
    def test_model_output_marks_are_taken_from_the_event_stream(self):
        from personal_assistant.workout.specialist import communicate_timed
        script = ('import sys,json,time;sys.stdin.read();'
                  'print(json.dumps({"type":"thread.started"}),flush=True);time.sleep(0.2);'
                  'print(json.dumps({"type":"item.completed","item":{"type":"reasoning"}}),flush=True);time.sleep(0.2);'
                  'print(json.dumps({"type":"item.completed","item":{"type":"agent_message"}}),flush=True)')
        process = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        started = time.monotonic()
        stdout, stderr, marks = communicate_timed(process, b'{}' * 50000, 30)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(len(stdout.splitlines()), 3)
        self.assertGreater(marks['first_output'], started)
        self.assertGreaterEqual(marks['first_text'] - marks['first_output'], 0.15)


if __name__ == '__main__':
    unittest.main()
