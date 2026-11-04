"""JEV dispatch integration with fake routing and worker execution only."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from personal_assistant.orchestrator.runtime import Orchestrator, write_json


class FakeRouter:
    def __init__(self, **choice):
        self.calls = []
        self.choice = {
            'action': 'dispatch', 'agent': 'codex', 'model': 'gpt-6-luna',
            'effort': 'low', 'task_type': 'general', 'profile': 'codex_luna_low',
            'confidence': 1.0, **choice,
        }
        self.error = None

    def decide(self, body, cancelled):
        self.calls.append(body)
        if self.error:
            raise self.error
        return self.choice


class FakeCLI:
    def __init__(self):
        self.calls = []
        self.starts = 0
        self.crash_after_result = False

    def run(self, prompt, directory, workspace, model, effort, cancelled,
            session=None, schema=None, instructions=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.calls.append({'prompt': prompt, 'session': session, 'schema': schema,
                           'instructions': instructions, 'model': model, 'effort': effort})
        record_file = directory/'record.json'
        if record_file.exists():
            return json.loads(record_file.read_text(encoding='utf-8'))
        self.starts += 1
        result = directory/'result.txt'
        result.write_text('PONG\n', encoding='utf-8')
        record = {'state': 'completed', 'session_id': session or 'fresh-worker-session',
                  'result': str(result), 'trace': str(directory/'events.jsonl')}
        write_json(record_file, record)
        if self.crash_after_result:
            self.crash_after_result = False
            raise KeyboardInterrupt('Simulated service crash after worker result persisted')
        return record


class JevDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cli, self.claude, self.router = FakeCLI(), FakeCLI(), FakeRouter()
        self.config = {'repository': str(self.root), 'orchestrator_dir': str(self.root/'runtime'),
                       'dispatcher_mode': 'jev'}
        self.agent = Orchestrator(self.config, cli=self.cli, claude=self.claude, router=self.router)
        self.availability = patch.object(self.agent, 'agent_availability', return_value={
            'codex': {'usable': True}, 'claude': {'usable': True}})
        self.availability.start()
        self.addCleanup(self.availability.stop)
        self.snapshot = patch('personal_assistant.orchestrator.runtime.capacity.snapshot', return_value={})
        self.capacity_snapshot = self.snapshot.start()
        self.addCleanup(self.snapshot.stop)

    def job(self, identifier='jev-task-first', command='Reply exactly PONG'):
        return {'id': identifier, 'payload': {'id': identifier, 'command': command,
                                            'timezone': 'Europe/Berlin'}}

    def execute(self, job=None):
        return self.agent.execute(job or self.job(), threading.Event())

    def test_one_fresh_worker_preserves_request_and_returns_exact_answer(self):
        request = 'Reply exactly PONG. Preserve this identifier: owner.detail@example.com.'
        with patch.object(self.agent, 'recent_tasks', side_effect=AssertionError('No history scan')):
            result = self.execute(self.job(command=request))
        self.assertEqual(result['result']['summary'], 'PONG\n')
        self.assertEqual(result['result']['executor'], 'agent.worker')
        self.assertEqual(len(self.router.calls), 1)
        self.assertEqual(len(self.cli.calls), 1)
        self.assertEqual(self.claude.calls, [])
        worker = self.cli.calls[0]
        self.assertEqual(worker['prompt'], request)
        self.assertIsNone(worker['schema'])
        self.assertIsNone(worker['session'])
        self.assertEqual((worker['model'], worker['effort']), ('gpt-6-luna', 'low'))
        self.capacity_snapshot.assert_called_once_with(self.config, refresh=False)
        body = self.router.calls[0]
        self.assertEqual(body['user_request'], request)
        self.assertNotIn('recent_tasks', body)
        self.assertNotIn('default_repository', body)

    def test_explicit_followup_resumes_worker_without_routing_again(self):
        first = self.execute()
        followup = self.job('jev-followup-task', 'Explain that answer')
        followup['payload']['resume_task'] = {'root_id': 'jev-task-first'}
        result = self.execute(followup)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['result']['resumed_session_id'], first['result']['workers'][0]['session_id'])
        self.assertEqual(self.cli.calls[-1]['session'], 'fresh-worker-session')
        self.assertEqual(len(self.router.calls), 1)
        self.assertEqual(len(self.cli.calls), 2)

    def test_recovery_reuses_decision_and_completed_worker_without_duplicate_effects(self):
        self.cli.crash_after_result = True
        with self.assertRaises(KeyboardInterrupt):
            self.execute()
        result = self.execute()
        self.assertEqual(result['result']['summary'], 'PONG\n')
        self.assertEqual(len(self.router.calls), 1)
        self.assertEqual(self.cli.starts, 1)
        calls = len(self.cli.calls)
        self.assertEqual(self.execute(), result)
        self.assertEqual(len(self.cli.calls), calls)

    def test_email_classification_forces_live_email_skill(self):
        skill = self.root/'skills/email/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: email\ndescription: Live email work\n---\nRead live Gmail threads.', encoding='utf-8')
        self.router.choice['task_type'] = 'email'
        self.agent = Orchestrator(self.config, cli=self.cli, claude=self.claude, router=self.router)
        with patch.object(self.agent, 'agent_availability', return_value={
                'codex': {'usable': True}, 'claude': {'usable': True}}):
            result = self.execute(self.job(command='Read my latest email'))
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['result']['workers'][0]['skills'], ['email'])
        self.assertIn('Read live Gmail threads.', self.cli.calls[0]['instructions'])

    def test_claude_email_selection_is_rejected_before_worker_launch(self):
        self.router.choice.update(agent='claude', model='claude-haiku-5-5',
                                  profile='claude_haiku_low', task_type='email')
        result = self.execute(self.job(command='Read my latest email'))
        self.assertEqual(result['state'], 'needs_input')
        self.assertEqual(self.cli.calls, [])
        self.assertEqual(self.claude.calls, [])
        self.assertIn('Email', result['result']['summary'])

    def test_router_failure_starts_no_worker_and_no_legacy_dispatcher(self):
        self.router.error = ValueError('Routing is unavailable')
        result = self.execute()
        self.assertEqual(result['state'], 'needs_input')
        self.assertIn('Routing is unavailable', result['result']['summary'])
        self.assertEqual(self.cli.calls, [])
        self.assertEqual(self.claude.calls, [])
        self.assertEqual(len(self.router.calls), 1)


if __name__ == '__main__':
    unittest.main()
