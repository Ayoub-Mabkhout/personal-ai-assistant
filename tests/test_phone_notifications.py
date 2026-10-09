from pathlib import Path
import tempfile
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from personal_assistant.relay.store import Queue
from personal_assistant.relay.notifications import NotificationPump
from personal_assistant.relay.tasks import task_router


class PhoneNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.now=1900000000
        self.queue=Queue(self.root/'agent.sqlite3',clock=lambda:self.now,serial=True,notifications=True)
        self.sent=[];self.fail=False
        def send(payload):
            if self.fail: raise OSError('Offline')
            self.sent.append(payload)
        self.pump=NotificationPump({'agent':self.queue},send,'https://assistant.example.com')

    def tearDown(self): self.temp.cleanup()

    def submit(self,identifier='task-test-123'):
        return self.queue.submit({'id':identifier,'command':'Run a test','timezone':'Europe/Berlin'})

    def test_phone_updates_queued_running_and_completed_without_duplicate_submissions(self):
        self.submit();self.pump.tick()
        self.assertIn('Laptop offline',self.sent[-1]['message'])
        tag=self.sent[-1]['data']['tag'];self.assertTrue(self.sent[-1]['data']['persistent'])
        self.assertEqual(self.sent[-1]['data']['ttl'],86400)
        self.submit();self.pump.tick();self.assertEqual(len(self.sent),1)
        self.queue.heartbeat('ready');self.pump.tick()
        self.assertIn('Waiting to start',self.sent[-1]['message'])
        job=self.queue.claim(120);self.pump.tick()
        self.assertIn('in progress',self.sent[-1]['title'])
        self.assertTrue(self.sent[-1]['data']['progress_indeterminate'])
        self.queue.finish(job['id'],job['lease_token'],'completed',{'summary':'Verified task result.'});self.pump.tick()
        self.assertEqual(self.sent[-1]['data']['tag'],tag)
        self.assertFalse(self.sent[-1]['data']['persistent'])
        self.assertIn('Verified task result',self.sent[-1]['message'])
        self.assertEqual(self.sent[-1]['data']['clickAction'],'https://assistant.example.com/tasks/agent/task-test-123')
        before=len(self.sent);self.pump.tick();self.assertEqual(len(self.sent),before)

    def test_retry_survives_restart_and_newer_state_supersedes_failed_update(self):
        self.fail=True;self.submit();self.pump.tick()
        row=self.queue.notification_rows()[0];self.assertEqual(row['attempts'],1)
        self.fail=False;self.pump.tick();self.assertFalse(self.sent)
        self.now+=6
        restored=Queue(self.queue.path,clock=lambda:self.now,notifications=True)
        pump=NotificationPump({'agent':restored},self.sent.append,'https://assistant.example.com')
        pump.tick();self.assertEqual(len(self.sent),1)
        self.fail=True;self.queue.heartbeat('ready');job=self.queue.claim();self.pump.tick()
        self.queue.finish(job['id'],job['lease_token'],'failed',{'summary':'Test failed.'})
        self.fail=False;self.pump.tick()
        self.assertIn('Task failed',self.sent[-1]['title'])
        self.assertFalse(self.queue.notification_rows())

    def test_disconnection_requeue_needs_input_cancel_and_expiry(self):
        self.submit();self.queue.heartbeat('ready');job=self.queue.claim(120);self.pump.tick()
        self.now+=61;self.pump.tick()
        self.assertIn('connection interrupted',self.sent[-1]['title'])
        self.now+=61;self.pump.tick();self.assertIn('queued',self.sent[-1]['title'])
        self.queue.heartbeat('ready');job=self.queue.claim()
        self.queue.finish(job['id'],job['lease_token'],'needs_input',{'summary':'Which file?'})
        self.pump.tick();self.assertIn('needs your input',self.sent[-1]['title'])
        self.assertIn('Which file?',self.sent[-1]['message'])
        self.submit('cancel-task');self.queue.cancel('cancel-task');self.pump.tick()
        self.assertIn('cancelled',self.sent[-1]['title'])
        from datetime import datetime,timezone
        expires=datetime.fromtimestamp(self.now+10,timezone.utc).isoformat()
        self.queue.submit({'id':'expiry-task','command':'Test','timezone':'Europe/Berlin','expires_at':expires})
        self.now+=11;self.pump.tick();self.assertIn('expired',self.sent[-1]['title'])

    def test_no_historical_notifications_and_stale_acceptance_cannot_hide_new_result(self):
        old=Queue(self.root/'old.sqlite3',clock=lambda:self.now)
        old.submit({'id':'historic-task','command':'Test','timezone':'Europe/Berlin'})
        enabled=Queue(old.path,clock=lambda:self.now,notifications=True)
        self.assertEqual(enabled.notification_rows(),[])
        self.submit();revision=self.queue.notification_rows()[0]['revision']
        self.queue.cancel('task-test-123')
        self.queue.notification_accepted('task-test-123',revision,'old-fingerprint')
        self.pump.tick();self.assertIn('cancelled',self.sent[-1]['title'])

    def test_task_details_require_login_and_exclude_private_worker_traces(self):
        self.submit();self.queue.heartbeat('ready');job=self.queue.claim()
        self.queue.finish(job['id'],job['lease_token'],'completed',{'summary':'Done','workers':[{'trace':'private-path'}]})
        app=FastAPI()
        def verify(token):
            if token!='valid-ha-token': raise OSError('Invalid')
        app.include_router(task_router({'agent':self.queue},'https://ha.example.com',self.root,user_verifier=verify))
        with TestClient(app) as client:
            self.assertEqual(client.get('/tasks/v1/agent/task-test-123').status_code,401)
            self.assertEqual(client.get('/tasks/v1/agent/task-test-123',headers={'Authorization':'Bearer bad'}).status_code,401)
            response=client.get('/tasks/v1/agent/task-test-123',headers={'Authorization':'Bearer valid-ha-token'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['summary'],'Done')
            self.assertNotIn('private-path',response.text)

    def test_task_page_serves_only_its_whitelisted_assets(self):
        app=FastAPI();assets=Path(__file__).resolve().parents[1]/'apps/tasks'
        app.include_router(task_router({'agent':self.queue,'command':self.queue},'https://ha.example.com',assets))
        with TestClient(app) as client:
            for name in ('app.js','theme.js','style.css'):
                response=client.get('/tasks/'+name)
                self.assertEqual(response.status_code,200,name)
                self.assertEqual(response.content,(assets/name).read_bytes())
            self.assertEqual(client.get('/tasks/daylight.js').content,(assets.parent/'shared/daylight.js').read_bytes())
            index=client.get('/tasks/agent/task-test-123')
            self.assertIn('/tasks/theme.js',index.text)
            self.assertIn("script-src 'self'",index.headers['content-security-policy'])
            self.assertEqual(client.get('/tasks/index.html').status_code,404)

    def test_notification_link_opens_only_its_task_and_cannot_mutate_queue(self):
        from personal_assistant.relay.task_links import TaskLinks
        from personal_assistant.relay.api import create_app
        links=TaskLinks.load(self.root/'task-links.key')
        self.assertEqual(TaskLinks.load(self.root/'task-links.key').token('agent','task-test-123'),links.token('agent','task-test-123'))
        def never_login(token): raise AssertionError('Task link must not require an HA login')
        app=FastAPI();app.include_router(task_router({'agent':self.queue,'command':self.queue},
            'https://ha.example.com',Path(__file__).resolve().parents[1]/'apps/tasks',user_verifier=never_login,task_links=links))
        self.submit();self.submit('other-task-123')
        token=links.token('agent','task-test-123')
        with TestClient(app) as client:
            self.assertEqual(client.get('/tasks/agent/task-test-123').status_code,200)
            response=client.get('/tasks/v1/agent/task-test-123',headers={'X-Task-View':token})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['id'],'task-test-123')
            self.assertEqual(client.get('/tasks/v1/agent/other-task-123',headers={'X-Task-View':token}).status_code,401)
            self.assertEqual(client.get('/tasks/v1/command/task-test-123',headers={'X-Task-View':token}).status_code,401)
            self.assertEqual(client.get('/tasks/v1/agent/task-test-123',headers={'X-Task-View':token+'x'}).status_code,401)
        protected=create_app(self.root/'api.sqlite3','s'*48,'w'*48,task_links=links)
        with TestClient(protected) as client:
            self.assertEqual(client.post('/v1/agent/prompts/task-test-123/cancel',headers={'Authorization':'Bearer '+token}).status_code,401)

    def test_refreshing_notification_does_not_rerun_completed_task(self):
        self.submit();self.queue.heartbeat('ready');job=self.queue.claim()
        self.queue.finish(job['id'],job['lease_token'],'completed',{'summary':'Done'})
        self.pump.tick();before=self.queue.get(job['id'])
        self.queue.notify_again(job['id']);self.pump.tick()
        after=self.queue.get(job['id'])
        self.assertEqual(before,after)
        self.assertEqual(len(self.sent),2)
        self.assertIsNone(self.queue.claim())


if __name__=='__main__': unittest.main()
