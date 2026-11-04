"""Workout coach engines: Codex/Claude selection, usage-limit fallback and the Claude answer contract."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from personal_assistant.workout import specialist
from personal_assistant.workout.specialist import EngineExhausted, engine_order, engines_ready, run_engine, run_once

CAPACITY = 'personal_assistant.orchestrator.capacity.'
FREE = {'available': True, 'five_hour': {'remaining_percent': 40.0}, 'weekly': {'remaining_percent': 70.0}, 'limit_reached': None}
SPENT = {'available': True, 'five_hour': {'remaining_percent': 0.0}, 'weekly': {'remaining_percent': 30.0}, 'limit_reached': 'primary'}
ANSWER = {'text': 'Keep the plan.', 'memory_summary': 'Synthetic narrative.', 'proposals': [], 'assessment_json': ''}

# Stands in for a CLI: records its arguments and stdin, then prints the stream the mode asks for.
FAKE_CLI = r'''
import json, os, sys
from pathlib import Path
record = Path(os.environ['FAKE_RECORD'])
record.write_text(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}), encoding='utf-8')
mode = os.environ['FAKE_MODE']
answer = {'text': 'Keep the plan.', 'memory_summary': 'Synthetic narrative.', 'assessment_json': '',
          'proposals': [{'kind': 'template', 'id': 'plan', 'base_revision': 0, 'data_json': '{"name": "Plan"}',
                         'reason': 'Synthetic reason.', 'deleted': False}]}
def emit(event): print(json.dumps(event), flush=True)
if mode == 'codex-limit':
    emit({'type': 'thread.started', 'thread_id': 'synthetic-thread'})
    emit({'type': 'turn.failed', 'error': {'message': 'Youâ€™ve hit your usage limit. Try again later.'}})
    sys.exit(1)
if mode == 'codex-broken':
    emit({'type': 'turn.failed', 'error': {'message': 'Synthetic transport error'}})
    sys.exit(1)
emit({'type': 'system', 'subtype': 'init', 'session_id': 'synthetic-claude-session'})
emit({'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected' if mode == 'claude-limit' else 'allowed',
      'rateLimitType': 'five_hour', 'unifiedWindows': {'five_hour': {'utilization': 0.5, 'resetsAt': 4102444800}}}})
if mode == 'claude-limit':
    emit({'type': 'result', 'subtype': 'error', 'is_error': True, 'api_error_status': 429,
          'result': 'Claude usage limit reached', 'session_id': 'synthetic-claude-session'})
    sys.exit(1)
emit({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'mcp__workout__workout_read', 'input': {'view': 'overview'}}]}})
emit({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'StructuredOutput', 'input': answer}]}})
final = {'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 'synthetic-claude-session', 'usage': {'output_tokens': 9}}
if mode == 'claude-fenced': final['result'] = '```json\n' + json.dumps(answer) + '\n```'
elif mode == 'claude-bad': final['structured_output'] = {'text': 'Missing the narrative'}
else: final.update(result=json.dumps(answer), structured_output=answer)
emit(final)
'''


class EngineSelectionTests(unittest.TestCase):
    def config(self, **values):
        return {'codex': 'synthetic-codex', **values}

    def test_auto_prefers_codex_while_it_has_allowance(self):
        with patch(CAPACITY+'codex', return_value=FREE), patch(CAPACITY+'claude_executable', return_value='claude'):
            self.assertEqual(engine_order(self.config(), {}), ['codex', 'claude'])

    def test_auto_skips_codex_when_capacity_reports_it_exhausted(self):
        with patch(CAPACITY+'codex', return_value=SPENT), patch(CAPACITY+'claude_executable', return_value='claude'):
            self.assertEqual(engine_order(self.config(), {}), ['claude'])
        reset = {**SPENT, 'five_hour': {'remaining_percent': 100.0, 'reset_since_observed': True}}
        with patch(CAPACITY+'codex', return_value=reset), patch(CAPACITY+'claude_executable', return_value=None):
            self.assertEqual(engine_order(self.config(), {}), ['codex'])

    def test_cached_claude_limit_and_cooldowns_are_respected(self):
        with patch(CAPACITY+'codex', return_value=FREE), patch(CAPACITY+'claude_executable', return_value='claude'), \
                patch(CAPACITY+'claude', return_value=SPENT):
            self.assertEqual(engine_order(self.config(orchestrator_dir='synthetic'), {}), ['codex'])
            self.assertEqual(engine_order(self.config(), {}), ['codex', 'claude'])  # no cache configured
            self.assertEqual(engine_order(self.config(), {'codex_retry_after': 4102444800}), ['claude'])

    def test_explicit_engine_and_validation(self):
        self.assertEqual(engine_order({'workout_coach_engine': 'claude'}, {}), ['claude'])
        self.assertEqual(engine_order({'workout_coach_engine': 'codex'}, {'codex_retry_after': 4102444800}), ['codex'])
        with self.assertRaises(ValueError): engine_order({'workout_coach_engine': 'gemini'}, {})
        self.assertFalse(engines_ready({'workout_coach_engine': 'gemini'}, {}))

    def test_rate_limited_codex_job_is_retried_on_claude(self):
        calls, state = [], {}
        def codex(*args):
            calls.append('codex'); raise EngineExhausted('codex')
        def claude(*args):
            calls.append('claude'); return {**ANSWER, '_model': 'claude-sonnet-5-5'}
        with patch(CAPACITY+'codex', return_value=FREE), patch(CAPACITY+'claude_executable', return_value='claude'):
            result = run_engine(self.config(), Path('synthetic.json'), state, {}, [], Path('.'), {'codex': codex, 'claude': claude})
            self.assertEqual(calls, ['codex', 'claude'])
            self.assertEqual(result['_engine'], {'engine': 'claude', 'model': 'claude-sonnet-5-5', 'fallback_from': ['codex']})
            self.assertGreater(state['codex_retry_after'], 0)
            # Later jobs go straight to Claude until the cooldown passes.
            run_engine(self.config(), Path('synthetic.json'), state, {}, [], Path('.'), {'codex': codex, 'claude': claude})
            self.assertEqual(calls, ['codex', 'claude', 'claude'])

    def test_other_codex_failures_are_not_retried_and_last_engine_limit_propagates(self):
        def broken(*args): raise RuntimeError('Codex trainer unavailable')
        def spent(*args): raise EngineExhausted('claude')
        with patch(CAPACITY+'codex', return_value=FREE), patch(CAPACITY+'claude_executable', return_value='claude'):
            with self.assertRaises(RuntimeError): run_engine(self.config(), Path('x'), {}, {}, [], Path('.'), {'codex': broken, 'claude': spent})
            state = {}
            with self.assertRaises(EngineExhausted):
                run_engine(self.config(workout_coach_engine='claude'), Path('x'), state, {}, [], Path('.'), {'claude': spent})
            self.assertIn('claude_retry_after', state)


class CoachLoopTests(unittest.TestCase):
    def client(self, job):
        calls = []
        class Client:
            def call(self, path, payload=None, method=None):
                calls.append((path.split('?')[0].rsplit('/', 1)[-1], payload))
                if '/trainer/claim' in path: return {'job': job, 'wait_seconds': 25}
                return {}
        return Client(), calls

    def test_coach_stays_ready_while_claude_can_answer_for_spent_codex(self):
        job = {'id': 'synthetic-job', 'token': 't'*20, 'photos': [], 'question': 'Plan?', 'context': {}}
        client, calls = self.client(job)
        def codex(*args): raise EngineExhausted('codex')
        def claude(*args): return {**ANSWER, '_model': 'claude-sonnet-5-5', '_marks': {}}
        def invoke(*args): return run_engine(*args, engines={'codex': codex, 'claude': claude})
        invoke.readiness = engines_ready
        with TemporaryDirectory() as directory, patch(CAPACITY+'codex', return_value=FREE), \
                patch(CAPACITY+'claude_executable', return_value='claude'):
            config = {'codex': 'synthetic-codex', 'workout_runtime_dir': directory}
            self.assertTrue(run_once(client, config, Path('synthetic.json'), {}, invoke))
            engine = json.loads((Path(directory)/'traces'/'synthetic-job.engine.json').read_text(encoding='utf-8'))
        self.assertEqual(calls[0], ('heartbeat', {'state': 'ready'}))
        answer = next(payload for name, payload in calls if name == 'answer')
        self.assertEqual(answer['text'], 'Keep the plan.')
        self.assertNotIn('state', answer)
        self.assertNotIn('engine', answer['timings'])
        self.assertEqual(engine['engine'], 'claude')
        self.assertEqual(engine['fallback_from'], ['codex'])

    def test_coach_reports_blocked_without_claiming_when_no_engine_has_allowance(self):
        client, calls = self.client(None)
        def invoke(*args): raise AssertionError('No engine should run')
        invoke.readiness = engines_ready
        poll = {}
        with patch(CAPACITY+'codex', return_value=SPENT), patch(CAPACITY+'claude_executable', return_value=None):
            self.assertFalse(run_once(client, {'codex': 'synthetic-codex'}, Path('x'), {}, invoke, poll))
        self.assertEqual(calls, [('heartbeat', {'state': 'blocked', 'detail': 'No coach engine has allowance'})])
        self.assertTrue(poll['blocked'])


class CliEngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root/'fake_cli.py').write_text(FAKE_CLI, encoding='utf-8')
        self.workspace = self.root/'workspace'
        self.workspace.mkdir()
        self.config = {'codex': 'synthetic-codex', 'claude': str(self.root/'fake_cli.py'),
                       'workout_runtime_dir': str(self.root/'runtime'), 'workout_timeout_seconds': 60}
        self.job = {'id': 'synthetic-job', 'token': 't'*20, 'photos': [], 'question': 'Plan?', 'context': {}}

    def run_cli(self, engine, mode, state, images=()):
        real = subprocess.Popen
        def launch(args, **options):
            # The fake CLI is a Python script; the engine passes its own arguments after the executable.
            options['env'] = {**options['env'], 'FAKE_MODE': mode, 'FAKE_RECORD': str(self.root/'record.json')}
            return real([sys.executable, str(self.root/'fake_cli.py'), *args[1:]], **options)
        with patch.object(specialist.subprocess, 'Popen', side_effect=launch):
            return engine(self.config, self.root/'config.json', state, self.job, list(images), self.workspace)

    def record(self):
        return json.loads((self.root/'record.json').read_text(encoding='utf-8'))

    def test_claude_answer_uses_workout_tools_schema_and_session(self):
        state = {'memory': 'Earlier narrative.'}
        photo = self.root/'abc.jpg'
        photo.write_bytes(b'\xff\xd8\xffsynthetic')
        self.job['photos'] = ['front']
        result = self.run_cli(specialist.run_claude, 'claude-ok', state, [photo])
        self.assertEqual(result['text'], 'Keep the plan.')
        self.assertEqual(result['proposals'][0]['kind'], 'template')
        self.assertEqual(result['_model'], 'claude-sonnet-5-5')
        self.assertLessEqual(result['_marks']['first_output'], result['_marks']['first_text'])
        self.assertEqual(state['claude_session'], 'synthetic-claude-session')
        argv = self.record()['argv']
        self.assertEqual(argv[argv.index('--tools')+1], '')
        self.assertEqual(argv[argv.index('--allowedTools')+1], 'mcp__workout__workout_read')
        self.assertEqual(json.loads(argv[argv.index('--json-schema')+1]), specialist.SCHEMA)
        self.assertIn('--strict-mcp-config', argv)
        self.assertNotIn('--resume', argv)
        servers = json.loads(Path(argv[argv.index('--mcp-config')+1]).read_text(encoding='utf-8'))['mcpServers']
        self.assertIn('personal_assistant.workout.tools', servers['workout']['args'])
        message = json.loads(self.record()['stdin'])['message']['content']
        self.assertEqual(json.loads(message[0]['text'])['previous_narrative'], 'Earlier narrative.')
        self.assertEqual(message[2]['source']['media_type'], 'image/jpeg')
        self.assertTrue((self.root/'runtime'/'traces'/'synthetic-job.claude.jsonl').is_file())
        # The next question resumes the same Claude conversation.
        self.run_cli(specialist.run_claude, 'claude-ok', state)
        argv = self.record()['argv']
        self.assertEqual(argv[argv.index('--resume')+1], 'synthetic-claude-session')

    def test_claude_answer_from_text_result_and_invalid_answers(self):
        self.assertEqual(self.run_cli(specialist.run_claude, 'claude-fenced', {})['memory_summary'], 'Synthetic narrative.')
        with self.assertRaises(ValueError): self.run_cli(specialist.run_claude, 'claude-bad', {})
        with self.assertRaises(ValueError): specialist.validate_answer({**ANSWER, 'proposals': [{'kind': 'diet', 'id': 'x'}]})

    def test_claude_usage_limit_is_reported_as_exhausted(self):
        with self.assertRaises(EngineExhausted) as raised: self.run_cli(specialist.run_claude, 'claude-limit', {})
        self.assertEqual(raised.exception.engine, 'claude')

    def test_codex_usage_limit_is_detected_from_its_error_events(self):
        with self.assertRaises(EngineExhausted) as raised: self.run_cli(specialist.run_model, 'codex-limit', {})
        self.assertEqual(raised.exception.engine, 'codex')
        with self.assertRaises(RuntimeError) as other: self.run_cli(specialist.run_model, 'codex-broken', {})
        self.assertNotIsInstance(other.exception, EngineExhausted)


if __name__ == '__main__':
    unittest.main()
