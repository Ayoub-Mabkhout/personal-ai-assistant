"""Iron League camera proof, scoped feed and comment routes."""
import base64
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

from personal_assistant.relay.store import Conflict, Missing
from personal_assistant.workout.api import routers
from personal_assistant.workout.identity import b64
from personal_assistant.workout.store import Workouts
from personal_assistant.workout.web import mount_train


WEB = '/train/api'
NATIVE = '/groceries/v1/mobile/workout'
DEVICE = {'Authorization': 'Bearer paired'}
AUTH = b64(b'a' * 32)
SALT = b64(b'b' * 16)


def image():
    with BytesIO() as output:
        with Image.new('RGB', (32, 24), color='purple') as jpeg:
            exif = jpeg.getexif()
            exif[270] = 'location metadata'
            jpeg.save(output, format='JPEG', exif=exif)
        return base64.b64encode(output.getvalue()).decode()


def workout(name='workout', revision=0, **changes):
    return {'mutation_id': 'finish_' + name, 'kind': 'workout', 'id': name,
            'base_revision': revision,
            'data': {'status': 'completed', 'name': 'Strength session', 'started_at': '2026-01-01T13:00:00Z',
                     'notes': 'private note', 'bodyweight_kg': 72, 'duration_seconds': 300,
                     'sets': [{'id': 'first', 'exercise_id': 'row', 'reps': 8, 'weight_kg': 30,
                               'notes': 'private set note'}], **changes}}


class WorkoutFeedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = Workouts(root / 'workout.db', require_proof=True)
        self.app = FastAPI()
        for error, status in ((Conflict, 409), (Missing, 404), (ValueError, 422)):
            async def handle(request, exc, code=status):
                return JSONResponse({'detail': str(exc)}, status_code=code)
            self.app.add_exception_handler(error, handle)

        def device(request: Request):
            if request.headers.get('Authorization') != 'Bearer paired':
                raise HTTPException(401)

        for router in routers(self.store, lambda: None, device):
            self.app.include_router(router)
        mount_train(self.app, self.store, lambda: None, root / 'no-assets',
                    device=device, require_identity=True)
        self.photo = image()

    def client(self, name=None):
        client = TestClient(self.app, base_url='https://train.test')
        self.addCleanup(client.close)
        if name is not None:
            response = client.post(WEB + '/auth/register',
                                   json={'name': name, 'auth_secret': AUTH, 'client_salt': SALT})
            self.assertEqual(response.status_code, 200, response.text)
        return client

    def finish(self, client, operation, *, share=True, prefix=WEB, photo=None, **kwargs):
        return client.post(prefix + '/workout-finish', json={'operation': operation,
                           'photo_base64': self.photo if photo is None else photo, 'share': share}, **kwargs)

    def test_required_completion_is_atomic_and_retry_safe(self):
        client = self.client('Athlete')
        self.assertEqual(client.get(WEB + '/workout-proof-policy').json(), {'required': True})
        op = workout()
        self.assertEqual(client.post(WEB + '/sync', json={'operations': [op]}).status_code, 428)
        self.assertEqual(client.get(WEB + '/entities/workout/workout').status_code, 404)
        self.assertEqual(self.finish(client, op, photo='broken!').status_code, 422)
        self.assertEqual(client.get(WEB + '/entities/workout/workout').status_code, 404)
        completed = self.finish(client, op, share=False)
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(self.finish(client, op, share=False).json(), completed.json())
        self.assertEqual(self.finish(client, op).status_code, 409)
        self.assertEqual(client.get(WEB + '/feed').json()['items'], [])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM workout_proofs').fetchone()[0], 0)
        revision = completed.json()['results'][0]['revision']
        edit = {**workout(revision=revision, name='workout'), 'mutation_id': 'retro_edit'}
        self.assertEqual(client.post(WEB + '/sync', json={'operations': [edit]}).status_code, 200)

    def test_explicit_sharing_feed_and_comments_follow_visibility(self):
        athlete, friend, guest = self.client('Athlete'), self.client('Friend'), self.client()
        response = self.finish(athlete, workout())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(friend.get(WEB + '/feed').json()['items'], [])
        athlete.patch(WEB + '/me', json={'share_progress': True})
        item, = friend.get(WEB + '/feed').json()['items']
        self.assertEqual(item['name'], 'Strength session')
        self.assertEqual(item['exercises'][0]['sets'][0]['reps'], 8)
        self.assertNotIn('private', str(item))
        self.assertNotIn('bodyweight', str(item))
        post_url = f"{WEB}/feed/{item['id']}"
        photo_url = item['photo_url']
        self.assertEqual(guest.get(photo_url).status_code, 401)
        photo = friend.get(photo_url)
        self.assertEqual(photo.status_code, 200)
        self.assertEqual(photo.headers['cache-control'], 'private, no-store')
        with Image.open(BytesIO(photo.content)) as jpeg:
            self.assertEqual(jpeg.format, 'JPEG')
            self.assertFalse(jpeg.getexif())
        self.assertEqual(friend.get(f"{WEB}/photos/{item['id']}").status_code, 404)
        self.assertEqual(friend.get(f"{WEB}/vault/records/photo/{item['id']}").status_code, 404)

        comments = post_url + '/comments'
        body = {'text': 'Nice work!', 'client_id': 'comment_1'}
        posted = friend.post(comments, json=body)
        self.assertEqual(posted.status_code, 200, posted.text)
        self.assertEqual(posted.json()['author']['name'], 'Friend')
        self.assertEqual(friend.post(comments, json=body).json(), posted.json())
        self.assertEqual(friend.get(WEB + '/feed').json()['items'][0]['comment_count'], 1)
        self.assertEqual(guest.get(comments).status_code, 401)
        athlete.patch(WEB + '/me', json={'share_progress': False})
        for url in (comments, photo_url):
            self.assertEqual(friend.get(url).status_code, 404)
        self.assertEqual(friend.post(comments, json=body).status_code, 404)
        athlete.patch(WEB + '/me', json={'share_progress': True})
        self.assertEqual(athlete.delete(f"{comments}/{posted.json()['id']}").status_code, 204)
        self.assertEqual(friend.post(comments, json=body).status_code, 409)
        self.assertEqual(friend.get(comments).json()['items'], [])

        revision = response.json()['results'][0]['revision']
        delete = {**workout(revision=revision), 'deleted': True, 'mutation_id': 'delete_workout'}
        self.assertEqual(athlete.post(WEB + '/sync', json={'operations': [delete]}).status_code, 200)
        self.assertEqual(friend.get(photo_url).status_code, 404)
        self.assertEqual(friend.get(comments).status_code, 404)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM workout_feed_comments').fetchone()[0], 0)

    def test_native_routes_require_pairing_and_share_feed(self):
        browser = self.client('Viewer')
        native = self.client()
        self.assertEqual(native.get(NATIVE + '/friends/feed').status_code, 401)
        self.assertEqual(native.get(NATIVE + '/workout-proof-policy', headers=DEVICE).json(), {'required': True})
        self.assertEqual(native.post(NATIVE + '/friends/me', headers=DEVICE, json={'share_progress': True}).status_code, 200)
        response = self.finish(native, workout(), prefix=NATIVE, headers=DEVICE)
        self.assertEqual(response.status_code, 200, response.text)
        web_item, = browser.get(WEB + '/feed').json()['items']
        item, = native.get(NATIVE + '/friends/feed', headers=DEVICE).json()['items']
        self.assertEqual(web_item['id'], item['id'])
        self.assertTrue(item['photo_url'].startswith(NATIVE + '/friends/feed/'))
        self.assertEqual(native.get(item['photo_url']).status_code, 401)
        self.assertEqual(native.get(item['photo_url'], headers=DEVICE).status_code, 200)

    def test_rollout_and_imports_leave_older_workouts_usable(self):
        client = self.client('Athlete')
        self.store.require_proof = False
        self.assertEqual(client.get(WEB + '/workout-proof-policy').json(), {'required': False})
        op = workout()
        self.assertEqual(client.post(WEB + '/sync', json={'operations': [op]}).status_code, 200)
        self.store.require_proof = True
        self.store.mutate([workout('legacy_import')], actor='import:strong_fixture')
        self.assertEqual(client.get(WEB + '/feed').json()['items'], [])
