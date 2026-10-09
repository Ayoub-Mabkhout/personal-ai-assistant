import hashlib
import importlib.util
from pathlib import Path
import unittest
from personal_assistant.worker.runtime import TransportError

spec = importlib.util.spec_from_file_location('verify_forwarded_task', Path(__file__).resolve().parents[1]/'scripts'/'verify_forwarded_task.py')
module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class FakeRelay:
    def __init__(self, jobs):self.jobs, self.paths = jobs, []
    def call(self, path):
        self.paths.append(path)
        task = path.rsplit('/', 1)[-1]
        if task not in self.jobs:raise TransportError(404)
        return self.jobs[task]


class VerifyForwardedTaskTests(unittest.TestCase):
    def setUp(self):
        self.request = 'Fix the dashboard features page'
        self.relay = FakeRelay({'task-12345678': {'state': 'queued', 'created': 1.0, 'payload': {'command': self.request}}})

    def test_matching_queue_entry_is_verified(self):
        sha = hashlib.sha256(self.request.encode()).hexdigest()
        result = module.verify(self.relay, 'task-12345678', sha.upper())
        self.assertTrue(result['verified'])
        self.assertEqual(result['request'], self.request)
        self.assertEqual(self.relay.paths, ['/v1/agent/prompts/task-12345678'])

    def test_changed_request_unknown_task_and_bad_id_are_rejected(self):
        self.assertFalse(module.verify(self.relay, 'task-12345678', '0'*64)['verified'])
        self.assertFalse(module.verify(self.relay, 'task-unknown1', None)['verified'])
        self.assertFalse(module.verify(self.relay, '../status', None)['verified'])
        self.assertEqual(len(self.relay.paths), 2)


if __name__ == '__main__':unittest.main()
