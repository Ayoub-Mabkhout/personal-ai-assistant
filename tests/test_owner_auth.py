import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient
from personal_assistant.relay.api import create_app
from personal_assistant.relay.owner_auth import COOKIE, password_record


class OwnerAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.password='isolated-test-password'
        (self.root/'owner-login.json').write_text(json.dumps(password_record('owner',self.password)))
        self.app=create_app(self.root/'queue.sqlite3','s'*40,'w'*40,
            groceries={'path':self.root/'groceries.sqlite3','internal_token':'g'*40,'assets':self.root})
        self.client=TestClient(self.app,base_url='https://assistant.example.test')

    def login(self, **values):
        return self.client.post('/auth/login',data={'username':'owner','password':self.password,**values},
            headers={'Origin':'https://assistant.example.test'},follow_redirects=False)

    def test_login_cookie_reads_cloud_store_without_exposing_credentials(self):
        self.assertEqual(self.client.get('/groceries/v1/list').status_code,401)
        response=self.login()
        self.assertEqual(response.status_code,303)
        cookie=response.headers['set-cookie']
        for flag in ('HttpOnly','Secure','SameSite=strict'):self.assertIn(flag,cookie)
        self.assertEqual(self.client.get('/groceries/v1/list').status_code,200)
        self.assertEqual(self.client.get('/tasks/v1/history').status_code,200)
        session=self.client.get('/auth/session')
        self.assertEqual(session.json(),{'authenticated':True})
        self.assertNotIn(self.password,session.text)
        with self.app.state.owner_auth.db() as db:
            row=db.execute('SELECT digest FROM owner_sessions').fetchone()[0]
        self.assertNotEqual(row,self.client.cookies.get(COOKIE))
        self.assertNotIn(self.password,(self.root/'owner-login.json').read_text())

    def test_logout_revokes_copied_cookie_and_cross_origin_writes_fail(self):
        self.login(); token=self.client.cookies.get(COOKIE)
        body={'id':'mutation-123','operation':'add','items':[{'name':'milk'}]}
        self.assertEqual(self.client.post('/groceries/v1/mutations',json=body).status_code,403)
        self.assertEqual(self.client.post('/groceries/v1/mutations',json=body,headers={'Origin':'https://attacker.example.test'}).status_code,403)
        self.assertEqual(self.client.post('/groceries/v1/mutations',json=body,headers={'Origin':'https://assistant.example.test'}).status_code,200)
        self.assertEqual(self.client.post('/auth/logout',headers={'Origin':'https://assistant.example.test'}).status_code,200)
        self.assertEqual(self.client.get('/auth/session',headers={'Cookie':COOKIE+'='+token}).status_code,401)

    def test_owner_bearer_works_for_headless_clients_and_worker_token_is_rejected(self):
        self.assertEqual(self.client.get('/groceries/v1/list',headers={'Authorization':'Bearer '+'s'*40}).status_code,200)
        self.assertEqual(self.client.get('/groceries/v1/list',headers={'Authorization':'Bearer '+'w'*40}).status_code,401)
        self.assertEqual(self.client.get('/tasks/v1/history',headers={'Authorization':'Bearer '+'s'*40}).status_code,200)

    def test_login_rejects_csrf_wrong_password_and_external_redirect(self):
        self.assertEqual(self.client.post('/auth/login',data={'username':'owner','password':self.password}).status_code,403)
        self.assertEqual(self.login(password='wrong-password').status_code,401)
        self.assertEqual(self.login(next='https://attacker.example.test').headers['location'],'/groceries/')
        self.assertEqual(self.login(next='/tasks/\\attacker').headers['location'],'/groceries/')

    def test_sessions_expire_and_login_attempts_are_bounded(self):
        self.login()
        with self.app.state.owner_auth.db() as db:db.execute('UPDATE owner_sessions SET expires=0')
        self.assertEqual(self.client.get('/auth/session').status_code,401)
        for attempt in range(10):self.assertEqual(self.login(password='wrong-password').status_code,401)
        self.assertEqual(self.login(password='wrong-password').status_code,429)
