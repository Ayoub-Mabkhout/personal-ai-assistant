import tempfile
from pathlib import Path
import unittest
from fastapi.testclient import TestClient
from personal_assistant.relay.api import create_app


class AgentQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.now=1900000000
        self.client=TestClient(create_app(self.root/'queue.sqlite3','s'*48,'w'*48,clock=lambda:self.now))
        self.owner={'Authorization':'Bearer '+'s'*48};self.worker={'Authorization':'Bearer '+'w'*48}

    def tearDown(self): self.client.close();self.temp.cleanup()

    def test_queues_are_independent_and_agent_claim_is_serial(self):
        for identifier in ['prompt-first','prompt-second']:
            response=self.client.post('/v1/agent/prompts',headers=self.owner,json={'id':identifier,'prompt':'Do this task'})
            self.assertEqual(response.status_code,201)
        self.assertEqual(self.client.post('/v1/agent/prompts',headers=self.owner,json={'id':'prompt-first','prompt':'Do this task'}).status_code,200)
        self.assertEqual(self.client.post('/v1/agent/prompts',headers=self.owner,json={'id':'prompt-first','prompt':'Changed'}).status_code,409)
        self.client.post('/v1/commands',headers=self.owner,json={'id':'programmatic-1','command':'Show my calendar','timezone':'Europe/Berlin'})
        for prefix in ['', '/agent']:
            self.client.post('/v1'+prefix+'/worker/heartbeat',headers=self.worker,json={'readiness':'ready'})
        first=self.client.post('/v1/agent/worker/claim',headers=self.worker,json={'lease_seconds':15}).json()['job']
        self.assertEqual(first['id'],'prompt-first')
        self.assertIsNone(self.client.post('/v1/agent/worker/claim',headers=self.worker,json={}).json()['job'])
        self.assertEqual(self.client.post('/v1/worker/claim',headers=self.worker,json={}).json()['job']['id'],'programmatic-1')
        self.now+=16
        reclaimed=self.client.post('/v1/agent/worker/claim',headers=self.worker,json={}).json()['job']
        self.assertEqual(reclaimed['id'],'prompt-first')
        self.assertNotEqual(first['lease_token'],reclaimed['lease_token'])
        self.assertEqual(self.client.post('/v1/agent/worker/prompt-first/result',headers=self.worker,json={
            'lease_token':first['lease_token'],'state':'completed','result':{}}).status_code,409)
        self.client.post('/v1/agent/worker/prompt-first/result',headers=self.worker,json={
            'lease_token':reclaimed['lease_token'],'state':'completed','result':{'summary':'done'}})
        self.assertEqual(self.client.post('/v1/agent/worker/claim',headers=self.worker,json={}).json()['job']['id'],'prompt-second')
        self.assertTrue((self.root/'agent-queue.sqlite3').is_file())

    def test_cancelled_prompt_cannot_be_claimed_and_private_api_requires_auth(self):
        self.assertEqual(self.client.get('/v1/agent/status').status_code,401)
        self.client.post('/v1/agent/prompts',headers=self.owner,json={'id':'prompt-cancel','prompt':'Stop'})
        self.client.post('/v1/agent/prompts/prompt-cancel/cancel',headers=self.owner)
        self.client.post('/v1/agent/worker/heartbeat',headers=self.worker,json={'readiness':'ready'})
        self.assertIsNone(self.client.post('/v1/agent/worker/claim',headers=self.worker,json={}).json()['job'])
