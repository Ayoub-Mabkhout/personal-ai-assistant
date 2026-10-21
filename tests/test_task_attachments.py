import base64
import hashlib
import json
from pathlib import Path
import tempfile
import io
import threading
from unittest.mock import patch
import unittest
from fastapi.testclient import TestClient
from personal_assistant.relay.api import create_app
from datetime import datetime, timezone


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.created=datetime.now(timezone.utc).isoformat()
        self.app=create_app(self.root/'queue.sqlite3','s'*40,'w'*40,groceries={'path':self.root/'groceries.sqlite3','internal_token':'g'*40,'assets':self.root})
        devices=self.app.state.mobile_events.devices
        def phone():return {'Authorization':'Bearer '+devices.exchange(devices.pairing()['code'],'Test phone')['token']}
        self.phone=phone();self.other=phone();self.worker={'Authorization':'Bearer '+'w'*40};self.owner={'Authorization':'Bearer '+'s'*40}
        self.client=TestClient(self.app)

    def tearDown(self):self.client.close();self.temp.cleanup()

    def upload(self,identifier='attachment-001',data=b'original picture bytes',phone=None,**overrides):
        value={'name':'Example picture.png','mime':'image/png','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),**overrides}
        header=base64.b64encode(json.dumps(value).encode()).decode()
        return self.client.put('/groceries/v1/mobile/task-attachments/'+identifier,content=data,headers={**(phone or self.phone),'X-Attachment-Manifest':header})

    def new_task(self,attachments=None):
        return self.client.post('/groceries/v1/mobile/tasks',json={'id':'new-task-0001','text':'Read the attached file','created_at':self.created,'attachments':attachments or ['attachment-001']},headers=self.phone)

    def test_original_available_to_worker_and_task_then_retry_is_exactly_once(self):
        self.assertEqual(self.upload().status_code,200)
        self.assertEqual(self.upload().status_code,200)
        self.assertEqual(self.client.get('/v1/agent/attachments/attachment-001',headers=self.worker).status_code,404)
        first=self.new_task();self.assertEqual(first.status_code,200,first.text)
        task=first.json()['task_id'];self.assertEqual(self.new_task().json()['task_id'],task)
        content=self.client.get('/v1/agent/attachments/attachment-001/content',headers=self.worker)
        self.assertEqual(content.content,b'original picture bytes')
        detail=self.client.get('/groceries/v1/mobile/tasks/agent/'+task,headers=self.phone).json()
        self.assertEqual(detail['attachments'][0]['name'],'Example picture.png')
        self.assertEqual(self.upload(data=b'different content').status_code,409)

    def test_bad_checksum_incomplete_upload_and_phone_scope_do_not_queue_a_task(self):
        self.assertEqual(self.upload(sha256='0'*64).status_code,422)
        self.assertEqual(self.new_task().status_code,404)
        self.assertEqual(self.upload('good-file-0001').status_code,200)
        response=self.client.post('/groceries/v1/mobile/tasks',json={'id':'other-task-001','text':'Read','created_at':self.created,'attachments':['good-file-0001']},headers=self.other)
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.client.get('/groceries/v1/mobile/task-attachments/good-file-0001',headers=self.other).status_code,404)
        self.assertEqual(self.client.get('/v1/agent/attachments/good-file-0001/content',headers=self.phone).status_code,401)
        self.assertEqual(self.upload('bad-name-0001',name='../file.txt').status_code,422)
        self.assertEqual(self.upload('big-file-0001',size=26*1024*1024).status_code,413)

    def test_streamed_upload_exceeds_json_limit_without_losing_original_bytes(self):
        data=b'example original bytes'*2000
        response=self.upload(data=data)
        self.assertEqual(response.status_code,200,response.text)
        self.new_task()
        self.assertEqual(self.client.get('/v1/agent/attachments/attachment-001/content',headers=self.worker).content,data)

    def test_followup_keeps_original_task_and_rejects_changed_attachment_replay(self):
        self.upload();root=self.new_task().json()['task_id'];self.upload('attachment-002',data=b'a second original')
        path='/groceries/v1/mobile/tasks/agent/'+root+'/followups'
        body={'id':'followup-0001','instruction':'Compare this one','attachments':['attachment-002']}
        result=self.client.post(path,json=body,headers=self.phone);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.post(path,json=body,headers=self.phone).json()['id'],result.json()['id'])
        self.assertEqual(self.client.post(path,json={**body,'attachments':[]},headers=self.phone).status_code,409)
        detail=self.client.get('/groceries/v1/mobile/tasks/agent/'+root,headers=self.phone).json()
        self.assertEqual(detail['turns'][0]['attachments'][0]['id'],'attachment-002')
        from personal_assistant.relay.store import Queue
        child=Queue(self.root/'agent-queue.sqlite3').get(result.json()['id'])
        self.assertEqual(child['payload']['resume_task']['root_id'],root)
        self.assertEqual(child['payload']['attachments'],['attachment-002'])

    def response_upload(self,task,identifier='reply-file-001',data=b'finished PDF',**overrides):
        manifest={'name':'Finished.pdf','mime':'application/pdf','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),**overrides}
        headers={**self.worker,'X-Attachment-Manifest':base64.b64encode(json.dumps(manifest).encode()).decode()}
        return self.client.put('/v1/agent/tasks/'+task+'/attachments/'+identifier,content=data,headers=headers)

    def test_response_originals_belong_to_their_answer_and_survive_store_reopen(self):
        self.upload();root=self.new_task().json()['task_id']
        first=self.response_upload(root);self.assertEqual(first.status_code,200,first.text)
        self.assertTrue(first.json()['created']);self.assertFalse(self.response_upload(root).json()['created'])
        child=self.client.post('/groceries/v1/mobile/tasks/agent/'+root+'/followups',headers=self.phone,json={'id':'response-followup','instruction':'Make an Excel too'}).json()['id']
        self.assertEqual(self.response_upload(child,'reply-file-002',name='Updated.xlsx').status_code,200)
        detail=self.client.get('/groceries/v1/mobile/tasks/agent/'+root,headers=self.phone).json()
        self.assertEqual(detail['attachments'][0]['name'],'Example picture.png')
        self.assertEqual([r['name'] for r in detail['response_attachments']],['Finished.pdf'])
        self.assertEqual([r['name'] for r in detail['turns'][0]['response_attachments']],['Updated.xlsx'])
        for auth in [self.phone,self.other]:
            response=self.client.get('/groceries/v1/mobile/task-attachments/reply-file-001/content',headers=auth)
            self.assertEqual(response.content,b'finished PDF')
        from personal_assistant.relay.task_attachments import TaskAttachments
        reopened=TaskAttachments(self.root/'task-attachments.sqlite3',self.root/'task-attachments')
        self.assertEqual(reopened.responses(root)[0]['id'],'reply-file-001')

    def test_response_upload_requires_service_auth_known_task_checksum_and_bounded_count(self):
        self.upload();root=self.new_task().json()['task_id']
        path='/v1/agent/tasks/'+root+'/attachments/reply-file-001'
        self.assertEqual(self.client.put(path,content=b'data',headers=self.phone).status_code,401)
        self.assertEqual(self.response_upload('missing-task-001').status_code,404)
        self.assertEqual(self.response_upload(root,sha256='0'*64).status_code,422)
        self.assertEqual(self.app.state.task_attachments.responses(root),[])
        for n in range(10):self.assertEqual(self.response_upload(root,'answer-file-%03d'%n).status_code,200)
        self.assertEqual(self.response_upload(root,'answer-file-011').status_code,422)
        self.assertEqual(len(self.app.state.task_attachments.responses(root)),10)

    def test_worker_helper_uploads_exact_original_and_is_idempotent(self):
        from personal_assistant.worker.task_files import attach
        self.upload();root=self.new_task().json()['task_id'];file=self.root/'Report.pdf';data=b'%PDF original report'*4000;file.write_bytes(data)
        testcase=self
        class Adapter:
            def call(self,path):
                from personal_assistant.worker.runtime import TransportError
                response=testcase.client.get(path,headers=testcase.worker)
                if response.status_code!=200:raise TransportError(response.status_code)
                return response.json()
            def upload(self,path,source,size,headers):
                response=testcase.client.put(path,content=source.read(),headers={**testcase.worker,**headers})
                testcase.assertEqual(response.status_code,200,response.text);return response.json()
        first=attach({},root,file,client=Adapter());second=attach({},root,file,client=Adapter())
        self.assertEqual(first['id'],second['id']);self.assertFalse(second['created'])
        self.assertEqual(self.client.get('/groceries/v1/mobile/task-attachments/'+first['id']+'/content',headers=self.phone).content,data)


class WorkerAttachmentTests(unittest.TestCase):
    def test_download_verifies_original_and_reuses_it_then_rejects_corrupt_transfer(self):
        from personal_assistant.orchestrator.attachments import download
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);token=root/'token';token.write_text('worker-test-token')
            data=b'original document';row={'id':'attachment-001','name':'document.pdf','mime':'application/pdf','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            calls=[]
            class Opener:
                def open(self,request,timeout):
                    calls.append(request.full_url)
                    self_token=request.get_header('Authorization')
                    if self_token!='Bearer worker-test-token':raise AssertionError('Missing worker auth')
                    return io.BytesIO(data if request.full_url.endswith('/content') else json.dumps(row).encode())
            config={'relay_url':'https://relay.example/relay','worker_token_file':str(token)}
            with patch('urllib.request.build_opener',return_value=Opener()):
                files=download(config,['attachment-001'],root/'job')
                self.assertEqual(Path(files[0]['path']).read_bytes(),data)
                download(config,['attachment-001'],root/'job')
                self.assertEqual(sum(url.endswith('/content') for url in calls),1)
                row['sha256']='0'*64
                with self.assertRaisesRegex(ValueError,'checksum'):download(config,['attachment-001'],root/'corrupt')
                self.assertEqual(list((root/'corrupt/attachments').iterdir()),[])

    def test_paths_reach_dispatch_worker_and_same_session_followup(self):
        from personal_assistant.orchestrator.runtime import Orchestrator
        from tests.test_orchestrator import FakeCLI
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fake=FakeCLI();config={'orchestrator_dir':str(root/'runtime'),'repository':str(root)}
            rows=[{'id':'attachment-001','name':'picture.png','path':str(root/'picture.png')}]
            agent=Orchestrator(config,cli=fake)
            with patch('personal_assistant.orchestrator.runtime.task_attachments.download',return_value=rows) as fetched:
                job={'id':'original-task','payload':{'id':'original-task','command':'Read attached','attachments':['attachment-001']}}
                result=agent.execute(job,threading.Event())
                self.assertEqual(json.loads(fake.calls[0]['prompt'])['attachments'],rows)
                self.assertIn(json.dumps(rows[0]['path']),fake.calls[1]['instructions'])
                self.assertIn('attach_task_file.py',fake.calls[1]['instructions'])
                self.assertIn('"task_id": "original-task"',fake.calls[1]['instructions'])
                session=result['result']['workers'][-1]['session_id']
                child={'id':'continue-task','payload':{'id':'continue-task','command':'Compare it','attachments':['attachment-001'],'resume_task':{'root_id':'original-task'}}}
                agent.execute(child,threading.Event())
                self.assertEqual(fake.calls[-1]['session'],session)
                self.assertIn(json.dumps(rows[0]['path']),fake.calls[-1]['instructions'])
                self.assertIn('"task_id": "continue-task"',fake.calls[-1]['instructions'])
                self.assertEqual(fetched.call_count,2)


if __name__=='__main__':unittest.main()
