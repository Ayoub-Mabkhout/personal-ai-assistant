"""The companion's native task history pages through MobileTasks while the web page uses /tasks/v1/history; both must page the same way."""
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from personal_assistant.relay.mobile_tasks import MobileTasks
from personal_assistant.relay.store import Queue
from personal_assistant.relay.tasks import task_router


class HistoryParity(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        now = [1000.0]
        self.queues = {kind: Queue(root / (kind + '.sqlite3'), clock=lambda: now[0]) for kind in ('agent', 'command')}
        for index in range(3):
            for kind, queue in self.queues.items():
                queue.submit({'id': '%s-task-%d' % (kind, index), 'command': 'Same timestamp %d' % index, 'timezone': 'UTC'})
            if index == 1:
                now[0] += 1
        app = FastAPI()
        app.include_router(task_router(self.queues, root, user_verifier=self.verify))
        self.client = TestClient(app)
        self.headers = {'Authorization': 'Bearer valid'}
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.client.close)

    @staticmethod
    def verify(token):
        if token != 'valid':
            raise OSError('rejected')

    def web_pages(self):
        pages, cursor = [], None
        for _ in range(10):
            params = {'limit': 2, **({'cursor': cursor} if cursor else {})}
            page = self.client.get('/tasks/v1/history', params=params, headers=self.headers).json()
            pages.append([item['kind'] + '/' + item['id'] for item in page['items']])
            cursor = page['next_cursor']
            if not cursor:
                return pages
        self.fail('the web history never reached its last page')

    def native_pages(self):
        native, pages, cursor = MobileTasks(self.queues), [], None
        for _ in range(10):
            page = native.history(cursor=cursor, limit=2)
            pages.append([item['kind'] + '/' + item['id'] for item in page['items']])
            cursor = page['next_cursor']
            if not cursor:
                return pages
        self.fail('the native history never reached its last page')

    def test_pages_hold_every_task_once_and_match(self):
        web, native = self.web_pages(), self.native_pages()
        flat = [task for page in web for task in page]
        self.assertEqual(len(flat), 6)
        self.assertEqual(len(set(flat)), 6, 'a task repeated or was skipped across pages')
        self.assertEqual(web, native)

    def test_history_needs_a_login_and_a_valid_cursor(self):
        self.assertEqual(self.client.get('/tasks/v1/history', headers={'Authorization': 'Bearer rejected'}).status_code, 401)
        self.assertEqual(self.client.get('/tasks/v1/history', params={'cursor': 'AAAA'}, headers=self.headers).status_code, 422)

    def test_search_covers_both_queues(self):
        found = self.client.get('/tasks/v1/history', params={'q': 'timestamp 2'}, headers=self.headers).json()['items']
        self.assertEqual(sorted(item['kind'] for item in found), ['agent', 'command'])


if __name__ == '__main__':
    unittest.main()
