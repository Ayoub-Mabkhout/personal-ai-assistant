from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from personal_assistant.relay.api import create_app
from personal_assistant.workout.store import Workouts


BASE = 'https://train.test'
TRAIN = '/train/api'
SUBMIT = 'synthetic-submit-' * 3
ADMIN = {'Authorization': 'Bearer '+SUBMIT}


class TrainWebTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        assets = self.root/'web'
        assets.mkdir()
        (assets/'index.html').write_text('<title>Train fixture</title>', encoding='utf-8')
        self.app = create_app(self.root/'queue.sqlite3', SUBMIT, 'synthetic-worker-' * 3, train_assets=assets)
        self.admin = self.client()

    def client(self):
        client = TestClient(self.app, base_url=BASE)
        self.addCleanup(client.close)
        return client

    def enroll(self, user_id=None):
        invite = self.admin.post('/v1/train/invites', headers=ADMIN, json={'user_id': user_id}).json()['invite']
        client = self.client()
        joined = client.post(TRAIN+'/join', json={'name': 'Same name', 'invite': invite})
        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertIn('HttpOnly', joined.headers['set-cookie'])
        self.assertIn('Secure', joined.headers['set-cookie'])
        self.assertEqual(joined.headers['cache-control'], 'private, no-store')
        self.assertEqual(self.admin.post(TRAIN+'/join', json={'name': 'Other', 'invite': invite}).status_code, 403)
        return client, joined.json()['id']

    def test_same_ids_keep_mutations_history_media_and_coaches_separate(self):
        first, first_id = self.enroll()
        second, second_id = self.enroll()
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(self.admin.get(TRAIN+'/overview').status_code, 401)
        self.assertEqual(self.admin.get('/v1/train/users').status_code, 401)
        for client, label in [(first, 'First private note'), (second, 'Second private note')]:
            payload = {'operations': [{'kind': 'workout', 'id': 'same-id', 'base_revision': 0,
                                       'mutation_id': 'same-mutation',
                                       'data': {'name': label, 'started_at': '2026-11-02', 'status': 'completed'}}]}
            self.assertEqual(client.post(TRAIN+'/sync', json=payload).status_code, 200)
            history = client.get(TRAIN+'/changes').json()['items']
            self.assertEqual([item['data']['name'] for item in history if item['kind']=='workout'], [label])
            self.assertEqual(client.get(TRAIN+'/entities/workout/same-id').json()['data']['name'], label)
        self.assertEqual(self.admin.get('/v1/workout/entities/workout/same-id', headers=ADMIN).status_code, 404)

        image = b'\xff\xd8\xff' + b'test' * 5000
        digest = hashlib.sha256(image).hexdigest()
        photo_path = TRAIN+'/photos/'+digest
        self.assertEqual(first.put(photo_path, content=image, headers={'Content-Type': 'image/jpeg'}).status_code, 200)
        self.assertEqual(second.get(photo_path).status_code, 404)

        first_worker = f'/v1/train/users/{first_id}/workout/trainer'
        second_worker = f'/v1/train/users/{second_id}/workout/trainer'
        for route in (first_worker, second_worker):
            self.assertEqual(self.admin.put(route+'/heartbeat', headers=ADMIN, json={'state': 'ready'}).status_code, 200)
        self.assertEqual(first.post(TRAIN+'/trainer/questions', json={'id': 'same-coach-question',
                         'text': 'First private question', 'context': {'not_before': 99999999999}}).status_code, 200)
        job = self.admin.post(first_worker+'/claim', headers=ADMIN).json()['job']
        self.assertEqual(job['question'], 'First private question')
        self.assertIsNone(self.admin.post(second_worker+'/claim', headers=ADMIN).json()['job'])
        self.assertEqual(second.get(TRAIN+'/trainer/conversation').json()['items'], [])
        self.assertIn(first.post(TRAIN+'/trainer/claim', json={}).status_code, (404, 405))

    def test_owner_link_sharing_and_same_origin(self):
        self.app.state.workouts.mutate([{'kind': 'workout', 'id': 'old-workout', 'base_revision': 0,
            'mutation_id': 'old-mutation', 'data': {'name': 'Private workout', 'started_at': '2026-11-02', 'status': 'completed'}}])
        owner, owner_id = self.enroll('owner')
        other, _ = self.enroll()
        self.assertEqual(owner.get(TRAIN+'/entities/workout/old-workout').status_code, 200)
        self.assertEqual(other.get(TRAIN+'/entities/workout/old-workout').status_code, 404)
        profile = TRAIN+'/profiles/'+owner_id
        self.assertEqual(other.get(profile).status_code, 404)
        self.assertEqual(owner.patch(TRAIN+'/me', json={'share_progress': True},
                                     headers={'Origin': 'https://other.test'}).status_code, 403)
        self.assertEqual(owner.patch(TRAIN+'/me', json={'share_progress': True}, headers={'Origin': BASE}).status_code, 200)
        shared = other.get(profile)
        self.assertEqual(shared.status_code, 200)
        self.assertEqual(shared.json()['completed_workouts'], 1)
        self.assertNotIn('Private workout', shared.text)
        owner.patch(TRAIN+'/me', json={'share_progress': False})
        self.assertEqual(other.get(profile).status_code, 404)
        self.assertEqual(len(other.get(TRAIN+'/standings').json()['items']), 2)
        self.assertIn('Train fixture', self.admin.get('/train/').text)

    def test_onboarding_preferences_and_coach_exercise_proposal(self):
        client, user_id = self.enroll()
        other, _ = self.enroll()
        self.assertFalse(client.get(TRAIN+'/me').json()['setup_complete'])
        self.assertTrue(client.patch(TRAIN+'/me', json={'setup_complete': True}).json()['setup_complete'])
        self.assertFalse(other.get(TRAIN+'/me').json()['setup_complete'])
        settings = TRAIN+'/reminders'
        self.assertFalse(client.get(settings).json()['roast'])
        self.assertFalse(client.get(settings).json()['scheduled_sprints'])
        sprint = {'kind':'sprint', 'id':'first-sprint', 'base_revision':0, 'mutation_id':'first-sprint',
                  'data':{'name':'First sprint', 'phase':'build', 'start':'2026-11-03',
                          'scheduled':[{'date':'2026-11-04', 'id':'day-one', 'starts_at':'2026-11-04T18:00:00+01:00',
                                        'template_id':'new-template'}]}}
        self.assertEqual(client.post(TRAIN+'/sync', json={'operations':[sprint]}).status_code, 409)
        client.patch(settings, json={'scheduled_sprints': True})
        self.assertFalse(other.get(settings).json()['scheduled_sprints'])
        worker = f'/v1/train/users/{user_id}/workout/trainer'
        self.admin.put(worker+'/heartbeat', headers=ADMIN, json={'state':'ready'}).raise_for_status()
        client.post(TRAIN+'/trainer/questions', json={'id':'setup-question', 'text':'Plan my first sprint'}).raise_for_status()
        job = self.admin.post(worker+'/claim', headers=ADMIN).json()['job']
        proposals = [
            {'kind':'exercise', 'id':'new-exercise', 'mutation_id':'new-exercise', 'base_revision':0,
             'data':{'name':'Cable Fly'}},
            {'kind':'template', 'id':'new-template', 'mutation_id':'new-template', 'base_revision':0,
             'data':{'name':'First workout', 'exercises':[{'exercise_id':'new-exercise'}]}},
            sprint,
        ]
        self.admin.put(worker+'/setup-question/answer', headers=ADMIN,
                       json={'token':job['token'], 'text':'Plan ready.', 'proposals':proposals}).raise_for_status()
        self.assertEqual(client.get(TRAIN+'/entities/exercise/new-exercise').status_code, 404)
        client.post(TRAIN+'/trainer/setup-question/approve').raise_for_status()
        self.assertEqual(client.get(TRAIN+'/entities/exercise/new-exercise').json()['data']['name'], 'Cable Fly')
        self.assertEqual(other.get(TRAIN+'/entities/exercise/new-exercise').status_code, 404)
        client.patch(settings, json={'scheduled_sprints': False})
        self.assertEqual(client.get(TRAIN+'/entities/sprint/first-sprint').status_code, 200)

    def test_old_database_keeps_owner_revision_and_import_columns(self):
        path = self.root/'legacy.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
                CREATE TABLE entities(kind TEXT,id TEXT,revision INTEGER,deleted INTEGER,data TEXT,updated REAL,PRIMARY KEY(kind,id));
                CREATE TABLE changes(revision INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,id TEXT,deleted INTEGER,data TEXT,at REAL,actor TEXT);
                CREATE TABLE imports(hash TEXT PRIMARY KEY,report TEXT,raw TEXT,at REAL);
                INSERT INTO entities VALUES('exercise','old',23,0,'{"name":"Old"}',1);
                INSERT INTO changes VALUES(23,'exercise','old',0,'{"name":"Old"}',1,'owner');
                INSERT INTO imports VALUES('old','{}','synthetic source',1);
            """)
        store = Workouts(path)
        self.assertEqual(store.get('exercise','old')['revision'], 23)
        self.assertEqual(store.changes(0)['cursor'], 23)
        self.assertEqual(store.original_import('old'), b'synthetic source')
        guest = store.for_user('synthetic-member')
        self.assertEqual(guest.changes(0)['items'], [])
        result = guest.mutate([{'kind':'exercise','id':'old','base_revision':0,
                                'mutation_id':'new-guest-change','data':{'name':'Guest'}}])[0]
        self.assertGreater(result['revision'], 23)
        self.assertEqual(Workouts(path).get('exercise','old')['data']['name'], 'Old')
