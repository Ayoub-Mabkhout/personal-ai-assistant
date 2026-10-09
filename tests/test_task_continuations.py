import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from personal_assistant.relay.store import Queue,Conflict
from personal_assistant.relay.tasks import task_router
from personal_assistant.relay.task_links import TaskLinks
from personal_assistant.relay.continuations import Continuations,Followup
from tests.test_orchestrator import FakeCLI
from personal_assistant.orchestrator.runtime import Orchestrator


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.queue=Queue(self.root/'agents.sqlite3',serial=True)
        self.queue.submit({'id':'original-task','command':'Original instruction','timezone':'Europe/Berlin'})
        self.links=TaskLinks(b'x'*32)
        app=FastAPI();app.include_router(task_router({'agent':self.queue},self.root,task_links=self.links))
        self.client=TestClient(app)
        self.view={'X-Task-View':self.links.token('agent','original-task')}

    def tearDown(self):self.client.close();self.temp.cleanup()

    def test_task_link_can_continue_only_its_own_conversation(self):
        page=self.client.get('/tasks/v1/agent/original-task',headers=self.view).json()
        auth={'X-Task-Followup':page['followup_token']}
        body={'id':'stable-followup','instruction':'A new instruction'}
        self.assertEqual(self.client.post('/tasks/v1/agent/original-task/followups',json=body,headers=self.view).status_code,401)
        self.assertEqual(self.client.post('/tasks/v1/agent/other-task/followups',json=body,headers=auth).status_code,401)
        reply=self.client.post('/tasks/v1/agent/original-task/followups',json=body,headers=auth)
        self.assertEqual(reply.status_code,200)
        self.assertEqual(reply.json()['state'],'queued')
        duplicate=self.client.post('/tasks/v1/agent/original-task/followups',json=body,headers=auth)
        self.assertEqual(reply.json()['id'],duplicate.json()['id']);self.assertFalse(duplicate.json()['created'])
        self.assertEqual(self.queue.get('original-task')['payload']['command'],'Original instruction')
        detail=self.client.get('/tasks/v1/agent/original-task',headers=self.view).json()
        self.assertEqual(len(detail['turns']),1)
        self.assertEqual(detail['turns'][0]['instruction'],body['instruction'])

    def test_receipt_recovers_crash_before_queue_submission_and_rejects_changed_retry(self):
        inbox=Continuations(self.queue);body=Followup(id='retry-followup',instruction='Only do the new work')
        original=self.queue.submit
        with patch.object(self.queue,'submit',side_effect=OSError('crash')):
            with self.assertRaises(OSError):inbox.accept('original-task',body)
        recovered=Continuations(self.queue)
        self.assertEqual(len(recovered.turns('original-task')),1)
        with self.assertRaises(Conflict):recovered.accept('original-task',Followup(id=body.id,instruction='Changed'))
        self.assertEqual(recovered.accept('original-task',body)[1],False)

    def test_worker_session_resumes_without_another_dispatch_and_survives_restart(self):
        fake=FakeCLI();config={'orchestrator_dir':str(self.root/'runtime'),'repository':str(self.root)}
        agent=Orchestrator(config,cli=fake)
        parent={'id':'original-task','payload':self.queue.get('original-task')['payload']}
        outcome=agent.execute(parent,threading.Event());session=outcome['result']['workers'][-1]['session_id']
        before=len(fake.calls)
        for identifier in ['continue-first','continue-second']:
            agent=Orchestrator(config,cli=fake)
            job={'id':identifier,'payload':{'id':identifier,'command':identifier,'resume_task':{'root_id':parent['id']}}}
            result=agent.execute(job,threading.Event())
            self.assertEqual(result['result']['resumed_session_id'],session)
            self.assertEqual(fake.calls[-1]['session'],session)
            self.assertEqual(json.loads(fake.calls[-1]['prompt'])['instruction'],identifier)
            self.assertNotIn('dispatch_protocol',json.loads(fake.calls[-1]['prompt']))
            calls=len(fake.calls);agent.execute(job,threading.Event());self.assertEqual(len(fake.calls),calls)
        self.assertEqual(len(fake.calls)-before,2)

    def test_crash_after_queue_write_recovers_one_turn(self):
        inbox=Continuations(self.queue);body=Followup(id='after-write-retry',instruction='One new turn')
        with patch.object(inbox,'accepted',side_effect=OSError('lost acknowledgement')):
            with self.assertRaises(OSError):inbox.accept('original-task',body)
        recovered=Continuations(self.queue)
        self.assertEqual(len(recovered.turns('original-task')),1)
        self.assertFalse(recovered.accept('original-task',body)[1])

    def test_continuation_notification_returns_to_original_conversation(self):
        from personal_assistant.relay.notifications import notification
        job,_=Continuations(self.queue).accept('original-task',Followup(id='notification-turn',instruction='Continue'))
        card=notification('agent',job,self.queue.status(),'https://assistant.example',task_links=self.links)
        self.assertEqual(card['data']['clickAction'],self.links.url('https://assistant.example','agent','original-task'))

    def test_history_requires_login_groups_turns_and_searches_followups(self):
        app=FastAPI();app.include_router(task_router({'agent':self.queue},self.root,
            user_verifier=lambda token:None,task_links=self.links))
        inbox=Continuations(self.queue)
        turn,_=inbox.accept('original-task',Followup(id='history-turn',instruction='Look for the invoice'))
        with TestClient(app) as client:
            self.assertEqual(client.get('/tasks/v1/history',headers=self.view).status_code,401)
            auth={'Authorization':'Bearer test-login'}
            result=client.get('/tasks/v1/history?q=invoice',headers=auth).json()
            self.assertEqual(len(result['items']),1)
            item=result['items'][0]
            self.assertEqual(item['id'],'original-task');self.assertEqual(item['state'],'queued')
            self.assertEqual(item['url'],'/tasks/agent/original-task')
            self.assertNotIn(turn['id'],json.dumps(result))
            self.assertEqual(client.get('/tasks/v1/history?q=notpresent',headers=auth).json()['items'],[])

    def test_history_cursor_does_not_repeat_tasks_with_equal_timestamps(self):
        queue=Queue(self.root/'same-time.sqlite3',clock=lambda:1000)
        for i in range(5):queue.submit({'id':'history-task-'+str(i),'command':'Test','timezone':'Europe/Berlin'})
        app=FastAPI();app.include_router(task_router({'agent':queue},self.root,user_verifier=lambda token:None))
        with TestClient(app) as client:
            auth={'Authorization':'Bearer test-login'};cursor=None;ids=[]
            for _ in range(3):
                url='/tasks/v1/history?limit=2'+('&cursor='+cursor if cursor else '')
                data=client.get(url,headers=auth).json();ids.extend(i['id'] for i in data['items']);cursor=data['next_cursor']
            self.assertEqual(len(ids),5);self.assertEqual(len(set(ids)),5);self.assertIsNone(cursor)
