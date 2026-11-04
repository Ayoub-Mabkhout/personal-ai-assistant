"""Agent dispatcher: Claude stand-in while Codex is exhausted, usage-limited or cooling down."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from personal_assistant.orchestrator import capacity
from personal_assistant.orchestrator.runtime import CLI, ClaudeCLI, Orchestrator, UsageLimited, untouched

CAPACITY = 'personal_assistant.orchestrator.capacity.'
FREE = {'available': True, 'five_hour': {'remaining_percent': 40.0}, 'weekly': {'remaining_percent': 70.0}, 'limit_reached': None}
SPENT = {'available': True, 'five_hour': {'remaining_percent': 0.0, 'resets_at': '2030-01-01T05:00:00+00:00'},
         'weekly': {'remaining_percent': 30.0}, 'limit_reached': 'primary'}


class FakeAgent:
    """One agent's CLI: answers dispatcher turns (schema) with a decision and runs workers."""
    def __init__(self, name, tasks=None, limited=False):
        self.name, self.calls, self.limited = name, [], limited
        self.tasks = tasks if tasks is not None else [{'agent': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'medium', 'task_type': 'general', 'skills': []}]

    def run(self, prompt, directory, workspace, model, effort, cancelled, session=None, schema=None, instructions=None):
        directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
        self.calls.append({'model': model, 'effort': effort, 'session': session, 'schema': bool(schema), 'prompt': prompt,
                           'instructions': instructions, 'directory': str(directory)})
        if self.limited and (schema or self.limited == 'all'):
            raise UsageLimited(self.name, observed=True)
        if schema:
            body = json.loads(prompt)
            if 'user_request' in body:
                output = {'action': 'dispatch', 'summary': 'Delegating.', 'forward_to': 'none', 'tasks': [
                    {'prompt': 'Write artifact', 'workspace': str(workspace), 'resume_session': '',
                     'expected_artifacts': ['artifact.txt'], **task} for task in self.tasks]}
            else:
                output = {'action': 'complete', 'summary': 'Artifact verified.', 'forward_to': 'none', 'tasks': []}
            identity, text = self.name+'-dispatcher', json.dumps(output)
        else:
            (Path(workspace)/'artifact.txt').write_text('Worker output', encoding='utf-8')
            identity, text = session or self.name+'-worker-'+directory.name, 'Artifact written.'
        (directory/'result.txt').write_text(text, encoding='utf-8')
        return {'state': 'completed', 'session_id': identity, 'model': model, 'result': str(directory/'result.txt'),
                'trace': str(directory/'events.jsonl')}


class DispatcherFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'codex.js').write_text('synthetic', encoding='utf-8')
        self.config = {'orchestrator_dir': str(self.root/'orchestrator'), 'repository': str(self.root),
                       'codex': str(self.root/'codex.js'), 'node': str(self.root/'codex.js')}
        self.luna, self.claude = FakeAgent('codex'), FakeAgent('claude')

    def agent(self, **config):
        return Orchestrator({**self.config, **config}, cli=self.luna, claude=self.claude)

    def job(self, identifier, command='Write a report'):
        return {'id': identifier, 'payload': {'id': identifier, 'command': command}}

    def run_job(self, identifier, reading=FREE, **config):
        with patch(CAPACITY+'codex', return_value=reading):
            return self.agent(**config).execute(self.job(identifier), threading.Event())

    def test_healthy_codex_keeps_luna_and_codex_workers(self):
        result = self.run_job('healthy-job')
        self.assertEqual(result['state'], 'completed')
        self.assertEqual([c['model'] for c in self.luna.calls], ['gpt-6-luna', 'gpt-6.1-sol', 'gpt-6-luna'])
        self.assertEqual(self.claude.calls, [])
        self.assertEqual(result['result']['orchestrator_session_id'], 'codex-dispatcher')
        self.assertNotIn('orchestrator_agent', result['result'])
        self.assertEqual(json.loads(self.luna.calls[0]['prompt'])['agent_availability']['codex'], {'usable': True})

    def test_exhausted_codex_moves_the_decision_and_workers_to_claude(self):
        self.luna.tasks = self.claude.tasks = [{'agent': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'medium', 'task_type': 'general', 'skills': []},
                                               {'agent': 'codex', 'model': 'gpt-6-astra', 'effort': 'ultra', 'task_type': 'research', 'skills': []}]
        result = self.run_job('spent-job', SPENT)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(self.luna.calls, [])
        dispatch = [c for c in self.claude.calls if c['schema']]
        self.assertEqual([(c['model'], c['effort']) for c in dispatch], [('claude-sonnet-5-5', 'low')]*2)
        self.assertIn('Claude stand-in', dispatch[0]['instructions'])
        self.assertFalse(json.loads(dispatch[0]['prompt'])['agent_availability']['codex']['usable'])
        workers = result['result']['workers']
        self.assertEqual([(w['agent'], w['model'], w['effort']) for w in workers],
                         [('claude', 'claude-sonnet-5-5', 'medium'), ('claude', 'claude-opus-5-5', 'max')])
        self.assertEqual(workers[1]['substituted_from']['model'], 'gpt-6-astra')
        self.assertEqual(result['result']['orchestrator_agent'], 'claude')
        # The Claude dispatcher session is stored apart from Luna's and resumed by the next task.
        saved = json.loads((self.root/'orchestrator'/'claude-session.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['session_id'], 'claude-dispatcher')
        self.assertFalse((self.root/'orchestrator'/'session.json').exists())
        self.assertIsNone(dispatch[0]['session']); self.assertEqual(dispatch[1]['session'], 'claude-dispatcher')

    def test_usage_limited_luna_decision_is_retried_on_claude_and_codex_cools_down(self):
        self.luna.limited = True
        self.claude.tasks = [{'agent': 'claude', 'model': 'claude-haiku-5-5', 'effort': 'low', 'task_type': 'general', 'skills': []}]
        result = self.run_job('limited-job')
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(len(self.luna.calls), 1)
        self.assertEqual(sum(c['schema'] for c in self.claude.calls), 2)
        self.assertIn('codex_retry_after', json.loads((self.root/'orchestrator'/'engines.json').read_text(encoding='utf-8')))
        # The cooldown skips Codex for the next task even though its capacity reading looks healthy.
        self.luna.limited = False
        self.run_job('cooling-job')
        self.assertEqual(len(self.luna.calls), 1)
        # After the cooldown Codex is tried again and a successful decision clears it.
        state =json.loads((self.root/'orchestrator'/'engines.json').read_text(encoding='utf-8'))
        state['codex_retry_after'] = 0
        (self.root/'orchestrator'/'engines.json').write_text(json.dumps(state), encoding='utf-8')
        self.luna.tasks = [{'agent': 'codex', 'model': 'gpt-6-luna', 'effort': 'low', 'task_type': 'general', 'skills': []}]
        self.assertEqual(self.run_job('recovered-job')['state'], 'completed')
        self.assertEqual(self.luna.calls[1]['model'], 'gpt-6-luna')
        self.assertNotIn('codex_retry_after', json.loads((self.root/'orchestrator'/'engines.json').read_text(encoding='utf-8')))

    def test_both_agents_limited_returns_needs_input(self):
        self.luna.limited = self.claude.limited = True
        result = self.run_job('both-limited')
        self.assertEqual(result['state'], 'needs_input')
        self.assertIn('usage limit', result['result']['summary'])
        state = json.loads((self.root/'orchestrator'/'engines.json').read_text(encoding='utf-8'))
        self.assertIn('codex_retry_after', state); self.assertIn('claude_retry_after', state)
        before = len(self.luna.calls)+len(self.claude.calls)
        result = self.run_job('both-cooling')
        self.assertIn('Neither Codex nor Claude', result['result']['summary'])
        self.assertEqual(len(self.luna.calls)+len(self.claude.calls), before)

    def test_email_assignment_waits_for_codex(self):
        self.claude.tasks = [{'agent': 'codex', 'model': 'gpt-6-sol', 'effort': 'low', 'task_type': 'email', 'skills': []}]
        result = self.run_job('email-job', SPENT)
        self.assertEqual(result['state'], 'needs_input')
        self.assertIn('Gmail', result['result']['summary'])
        self.assertFalse([c for c in self.claude.calls if not c['schema']])

    def test_explicit_engine_settings(self):
        self.claude.tasks = [{'agent': 'claude', 'model': 'claude-sonnet-5-5', 'effort': 'low', 'task_type': 'general', 'skills': []}]
        self.run_job('claude-mode', dispatcher_engine='claude', dispatcher_claude_model='claude-haiku-5-5')
        self.assertEqual(self.luna.calls, [])
        self.assertEqual(self.claude.calls[0]['model'], 'claude-haiku-5-5')
        result = self.run_job('bad-mode', dispatcher_engine='gemini')
        self.assertEqual(result['state'], 'needs_input')

    def continuation(self, identifier, reading):
        job = {'id': identifier, 'payload': {'id': identifier, 'command': 'Also add a summary', 'resume_task': {'root_id': 'parent-task'}}}
        with patch(CAPACITY+'codex', return_value=reading):
            return self.agent().execute(job, threading.Event())

    def test_follow_up_on_codex_worker_continues_on_claude_while_codex_is_exhausted(self):
        self.run_job('parent-task')
        worker_session = 'codex-worker-worker-0-0'
        result = self.continuation('follow-up-one', SPENT)
        self.assertEqual(result['state'], 'completed')
        moved = result['result']['workers'][0]
        self.assertEqual((moved['agent'], moved['model']), ('claude', 'claude-sonnet-5-5'))
        self.assertEqual(moved['fallback_from']['session_id'], worker_session)
        self.assertIsNone(self.claude.calls[-1]['session'])
        self.assertIn('fresh Claude session', self.claude.calls[-1]['instructions'])
        # The next follow-up resumes the Claude stand-in session, even once Codex is back.
        self.continuation('follow-up-two', FREE)
        self.assertEqual(self.claude.calls[-1]['session'], moved['session_id'])
        self.assertEqual(len([c for c in self.luna.calls if not c['schema']]), 1)

    def test_usage_limited_follow_up_moves_only_when_codex_did_nothing(self):
        self.run_job('parent-task')
        original = self.luna.run
        def limited(prompt, directory, *args, **kwargs):
            if 'continuation' in str(directory):
                Path(directory).mkdir(parents=True, exist_ok=True)
                (Path(directory)/'events.jsonl').write_text(self.trace, encoding='utf-8')
                raise UsageLimited('codex', observed=True)
            return original(prompt, directory, *args, **kwargs)
        self.luna.run = limited
        self.trace = json.dumps({'type': 'turn.failed', 'error': {'message': 'usage limit'}})+'\n'
        self.assertEqual(self.continuation('follow-up-clean', FREE)['result']['workers'][0]['agent'], 'claude')
        # Start over from the Codex worker (the clean case moved the conversation to Claude).
        (self.root/'orchestrator'/'engines.json').unlink()
        (self.root/'orchestrator'/'jobs'/'parent-task'/'conversation.json').unlink()
        self.trace = json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution'}})+'\n'
        result = self.continuation('follow-up-dirty', FREE)
        self.assertEqual(result['state'], 'needs_input')
        self.assertTrue(result['result']['reconciliation_required'])


FAKE_CLAUDE = r'''
import json, os, sys
from pathlib import Path
Path(os.environ['FAKE_RECORD']).write_text(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}), encoding='utf-8')
def emit(event): print(json.dumps(event), flush=True)
mode = os.environ['FAKE_MODE']
emit({'type': 'system', 'subtype': 'init', 'session_id': 'claude-dispatch-session'})
emit({'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected' if mode == 'limit' else 'allowed', 'rateLimitType': 'five_hour',
      'unifiedWindows': {'five_hour': {'utilization': 0.5, 'resetsAt': 4102444800}}}})
if mode == 'limit':
    emit({'type': 'result', 'is_error': True, 'api_error_status': 429, 'result': 'limit', 'session_id': 'claude-dispatch-session'})
    sys.exit(1)
decision = {'action': 'complete', 'summary': 'Done.', 'forward_to': 'none', 'tasks': []}
emit({'type': 'result', 'is_error': False, 'session_id': 'claude-dispatch-session', 'result': 'ok', 'structured_output': decision})
'''

FAKE_CODEX = r'''
import json, sys
sys.stdin.read()
print(json.dumps({'type': 'thread.started', 'thread_id': 'luna'}), flush=True)
print(json.dumps({'type': 'turn.failed', 'error': {'message': "You’ve hit your usage limit. Try again later."}}), flush=True)
sys.exit(1)
'''


class CLIUsageLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'fake_claude.py').write_text(FAKE_CLAUDE, encoding='utf-8')
        (self.root/'fake_codex.py').write_text(FAKE_CODEX, encoding='utf-8')
        self.config = {'claude': str(self.root/'fake_claude.py'), 'codex': str(self.root/'fake_codex.py'),
                       'orchestrator_dir': str(self.root/'orchestrator')}

    def launch(self, script, mode):
        real = subprocess.Popen
        def start(args, **options):
            options['env'] = {**options['env'], 'FAKE_MODE': mode, 'FAKE_RECORD': str(self.root/'record.json')}
            return real([sys.executable, str(self.root/script), *args[1:]], **options)
        return patch('subprocess.Popen', side_effect=start)

    def test_claude_dispatcher_call_is_structured_and_tool_less(self):
        schema = {'type': 'object'}
        with self.launch('fake_claude.py', 'ok'):
            record = ClaudeCLI(self.config).run('{}', self.root/'turn', self.root, 'claude-sonnet-5-5', 'low', threading.Event(),
                                                session='earlier', schema=schema, instructions='Dispatch.')
        self.assertEqual(json.loads(Path(record['result']).read_text(encoding='utf-8'))['action'], 'complete')
        self.assertEqual(record['session_id'], 'claude-dispatch-session')
        argv = json.loads((self.root/'record.json').read_text(encoding='utf-8'))['argv']
        self.assertEqual(argv[argv.index('--tools')+1], '')
        self.assertEqual(json.loads(argv[argv.index('--json-schema')+1]), schema)
        self.assertEqual(argv[argv.index('--permission-mode')+1], 'dontAsk')
        self.assertEqual(argv[argv.index('--resume')+1], 'earlier')
        self.assertIn('--system-prompt-file', argv); self.assertIn('--strict-mcp-config', argv)
        self.assertNotIn('bypassPermissions', argv)

    def test_usage_limits_are_detected_and_replayed_without_a_new_call(self):
        with self.launch('fake_claude.py', 'limit'):
            with self.assertRaises(UsageLimited) as raised:
                ClaudeCLI(self.config).run('{}', self.root/'claude-turn', self.root, 'claude-sonnet-5-5', 'low', threading.Event(), schema={})
        self.assertEqual(raised.exception.agent, 'claude'); self.assertTrue(raised.exception.observed)
        with self.launch('fake_codex.py', 'limit') as popen:
            with self.assertRaises(UsageLimited) as raised:
                CLI(self.config).run('{}', self.root/'codex-turn', self.root, 'gpt-6-luna', 'low', threading.Event(), schema={})
            self.assertEqual(raised.exception.agent, 'codex')
            self.assertTrue(untouched(self.root/'codex-turn'))
            calls = popen.call_count
            with self.assertRaises(UsageLimited) as replay:
                CLI(self.config).run('{}', self.root/'codex-turn', self.root, 'gpt-6-luna', 'low', threading.Event(), schema={})
            self.assertFalse(replay.exception.observed); self.assertEqual(popen.call_count, calls)

    def test_limit_detection_ignores_answer_text(self):
        answer = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Your usage limit is fine'}}]
        self.assertFalse(capacity.codex_limited(answer, 'transport error'))
        self.assertTrue(capacity.codex_limited([{'type': 'error', 'message': 'Rate limit reached'}]))
        self.assertFalse(capacity.claude_limited([{'type': 'result', 'is_error': False, 'result': 'quota talk'}]))


if __name__ == '__main__':
    unittest.main()
