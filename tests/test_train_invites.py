"""Invites created from the owner's phone, and what they let someone do once password sign-in is on."""
import base64
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from personal_assistant.relay.store import Conflict, Missing
from personal_assistant.workout.store import Workouts
from personal_assistant.workout.web import Accounts, mount_train

AUTH = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip('=')
SALT = base64.urlsafe_b64encode(bytes(range(16))).decode().rstrip('=')
DEVICE = '/groceries/v1/mobile/workout/friends/invites'


class PhoneInviteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.workouts = Workouts(Path(temp.name) / 'workouts.sqlite3')
        app = FastAPI()
        for error, status in ((Conflict, 409), (Missing, 404), (ValueError, 422)):
            async def handle(request, exc, code=status): return JSONResponse({'detail': str(exc)}, status_code=code)
            app.add_exception_handler(error, handle)

        def device(request: Request):
            if request.headers.get('Authorization') != 'Bearer phone':
                raise HTTPException(401, 'Pair the phone first.')
        mount_train(app, self.workouts, lambda: None, Path(temp.name) / 'no-assets', device=device, require_identity=True)
        self.client = TestClient(app, base_url='https://train.test'); self.addCleanup(self.client.close)

    def invite(self, user_id=None, token='phone'):
        return self.client.post(DEVICE, json={'user_id': user_id}, headers={'Authorization': 'Bearer ' + token})

    def register(self, name, invite):
        return self.client.post('/train/api/auth/register', json={'name': name, 'auth_secret': AUTH, 'client_salt': SALT, 'invite': invite})

    def test_only_the_paired_phone_can_create_invites(self):
        self.assertEqual(self.invite(token='someone-else').status_code, 401)

    def test_a_phone_invite_lets_a_new_member_register_once(self):
        response = self.invite(); self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['expires_in_days'], 7)
        self.assertEqual(self.register('New Friend', response.json()['invite']).status_code, 200)
        self.assertEqual(self.register('Another Friend', response.json()['invite']).status_code, 403)

    def test_a_phone_invite_for_a_member_restores_their_sign_in(self):
        member, _ = Accounts(self.workouts).join('Locked Out')
        response = self.invite(member['id']); self.assertEqual(response.status_code, 200)
        signed = self.register('Locked Out', response.json()['invite'])
        self.assertEqual((signed.status_code, signed.json()['id']), (200, member['id']))
        self.assertEqual(self.invite('f' * 32).status_code, 404)


if __name__ == '__main__':
    unittest.main()
