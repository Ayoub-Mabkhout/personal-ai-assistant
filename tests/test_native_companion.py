import base64
import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from personal_assistant.groceries.mobile import Devices
from personal_assistant.relay.api import create_app
from personal_assistant.relay.mobile_push import MobileEventStore, CompanionSender, MobilePushPump, FcmPush
from personal_assistant.relay.mobile_tasks import MobileTasks
from personal_assistant.relay.notifications import notification
from personal_assistant.relay.continuations import Followup
from personal_assistant.relay.store import Queue


class NativeTests(unittest.TestCase):
    def test_native_authenticated_history_detail_and_same_session_followup(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            app = create_app(path/'queue.sqlite3', 'o'*40, 'w'*40,
                             groceries={'path': path/'groceries.sqlite3', 'internal_token': 'g'*40,
                                        'ha_url': 'http://homeassistant:8123', 'assets': path})
            devices = app.state.mobile_events.devices
            phone = devices.exchange(devices.pairing()['code'], 'Phone')
            client = TestClient(app)
            owner = {'Authorization': 'Bearer '+'o'*40}
            paired = {'Authorization': 'Bearer '+phone['token']}
            result = client.post('/v1/agent/prompts', headers=owner,
                                 json={'id': 'original-agent-task', 'prompt': 'Find a document'}).json()
            self.assertEqual(result['job']['state'], 'queued')
            history = client.get('/groceries/v1/mobile/tasks', headers=paired).json()
            self.assertEqual(history['items'][0]['request'], 'Find a document')
            detail = client.get('/groceries/v1/mobile/tasks/agent/original-agent-task', headers=paired).json()
            self.assertEqual(detail['original_request'], 'Find a document')
            self.assertNotIn('payload', detail)
            self.assertNotIn('followup_token', detail)
            body = {'id': 'same-turn-id-123', 'instruction': 'Use the latest copy'}
            first = client.post('/groceries/v1/mobile/tasks/agent/original-agent-task/followups', headers=paired, json=body).json()
            second = client.post('/groceries/v1/mobile/tasks/agent/original-agent-task/followups', headers=paired, json=body).json()
            self.assertEqual(first['id'], second['id'])
            self.assertFalse(second['created'])
            child = client.get('/v1/agent/prompts/'+first['id'], headers=owner).json()
            self.assertEqual(child['payload']['resume_task'], {'root_id': 'original-agent-task'})
            self.assertEqual(child['payload']['command'], body['instruction'])
            self.assertEqual(client.post('/v1/agent/prompts', headers=paired, json={'id':'forbidden-task','prompt':'Test'}).status_code, 401)
            self.assertEqual(client.get('/groceries/v1/mobile/tasks').status_code, 401)
            devices.revoke(phone['id'])
            self.assertEqual(client.get('/groceries/v1/mobile/tasks', headers=paired).status_code, 401)

    def test_grouped_history_pagination_and_root_answer_survive_followup(self):
        with tempfile.TemporaryDirectory() as d:
            now = [1000.0]
            queues = {kind: Queue(Path(d)/(kind+'.sqlite3'), clock=lambda: now[0]) for kind in ('agent', 'command')}
            tasks = MobileTasks(queues)
            for kind in queues:
                queues[kind].submit({'id': kind+'-original-task', 'command': 'Same timestamp', 'timezone': 'UTC'})
            first = tasks.history(limit=1)
            second = tasks.history(cursor=first['next_cursor'], limit=1)
            self.assertNotEqual(first['items'][0]['id'], second['items'][0]['id'])
            queues['agent'].heartbeat('ready')
            job = queues['agent'].claim(60)
            queues['agent'].finish(job['id'], job['lease_token'], 'completed', {'summary':'Original answer'})
            tasks.followup('agent', 'agent-original-task', Followup(id='followup-id-001', instruction='Another question'))
            detail = tasks.detail('agent', 'agent-original-task')
            self.assertEqual(detail['original_summary'], 'Original answer')
            self.assertEqual(len(detail['turns']), 1)
            self.assertEqual(len(tasks.history()['items']), 2)
            self.assertEqual(tasks.history(query='Another')['items'][0]['id'], 'agent-original-task')

    def test_native_journal_dedup_receipts_revocation_and_provider_retry(self):
        with tempfile.TemporaryDirectory() as d:
            now = [1000.0]
            devices = Devices(Path(d)/'phones.sqlite3', clock=lambda: now[0])
            phone = devices.exchange(devices.pairing()['code'], 'Phone')
            store = MobileEventStore(devices)
            store.register(phone['id'], 'fcm', 'registration-token'*10)
            payload = {'type':'task', 'title':'Task queued', 'task_id':'test-task-001'}
            store.enqueue(payload)
            store.enqueue(payload)
            self.assertEqual(len(store.events(phone['id'])['items']), 1)
            failed = MobilePushPump(store, lambda row: (_ for _ in ()).throw(OSError()))
            failed.tick()
            self.assertEqual(store.pending(), [])
            now[0] += 11
            sent = []
            MobilePushPump(store, lambda row: sent.append(row['id'])).tick()
            self.assertEqual(len(sent), 1)
            self.assertEqual(store.pending(), [])
            self.assertEqual(store.status(phone['id'])['pending'], 1)  # acceptance != receipt
            row = store.events(phone['id'])['items'][0]
            store.receipt(phone['id'], row['sequence'])
            self.assertEqual(store.status(phone['id'])['pending'], 0)
            with self.assertRaises(ValueError): store.receipt(phone['id'], row['sequence']+1)
            store.enqueue({'type':'task', 'title':'New task'})
            devices.revoke(phone['id'])
            self.assertEqual(store.pending(), [])

    def test_sender_routes_tasks_alarm_target_reminders_and_unique_releases(self):
        with tempfile.TemporaryDirectory() as d:
            devices = Devices(Path(d)/'phones.sqlite3')
            phones = [devices.exchange(devices.pairing()['code'], 'Phone') for _ in range(2)]
            store = MobileEventStore(devices)
            sender = CompanionSender(store)
            queue = Queue(Path(d)/'agent.sqlite3')
            job = queue.submit({'id':'original-task-123', 'command':'Question', 'timezone':'UTC'})[0]
            push = notification('agent', job, queue.status(), 'https://example.test')
            sender(push); sender(push)
            sender({'title':'Calendar reminder', 'message':'Appointment', 'data':{'tag':'assistant-calendar-reminder123'}})
            sender({'title':'Phone alarm request', 'message':'07:30', 'data':{'tag':'assistant-alarm-alarm123','phone_id':phones[0]['id'],'ttl':600}})
            for version in (1, 2):
                sender({'message':'command_broadcast_intent','data':{'version_code':version,'sha256':str(version)*64}})
            first = store.events(phones[0]['id'])['items']
            second = store.events(phones[1]['id'])['items']
            self.assertEqual(len(first), 5)
            self.assertEqual(len(second), 4)
            task = first[0]['payload']
            self.assertEqual(task['task_id'], job['id'])
            self.assertNotIn('clickAction', task)
            self.assertEqual(task['state'], 'queued')

    def test_fcm_hint_has_no_private_content_and_scoped_jwt(self):
        with tempfile.TemporaryDirectory() as d:
            account = Path(d)/'account.json'
            account.write_text(json.dumps({'type':'service_account','project_id':'demo-project','client_email':'sender@example.test','private_key':'test'}))
            calls = []
            def request(url, body, headers):
                calls.append((url,body,headers))
                return {'access_token':'mock-access', 'expires_in':3600} if url.endswith('/token') else {'name':'accepted'}
            provider = FcmPush({'service_account_file':str(account)},requester=request,signer=lambda value:b'signature',clock=lambda:1000)
            provider({'id':'event-id-123','token':'phone-token','expires':1060,'payload':'Private task answer'})
            encoded = urllib_parse(calls[0][1])['assertion'][0].split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
            self.assertEqual(claims['scope'],'https://www.googleapis.com/auth/firebase.messaging')
            sent = json.loads(calls[1][1])
            self.assertEqual(sent['message']['data'], {'event_id':'event-id-123','type':'assistant_event'})
            self.assertNotIn('Private task', calls[1][1].decode())
            self.assertEqual(sent['message']['android']['ttl'], '60s')

    def test_snooze_is_phone_scoped_idempotent_and_not_skipped_by_later_events(self):
        with tempfile.TemporaryDirectory() as d:
            now = [1000.0]
            devices = Devices(Path(d)/'phones.sqlite3', clock=lambda: now[0])
            phone = devices.exchange(devices.pairing()['code'], 'Phone')
            other = devices.exchange(devices.pairing()['code'], 'Other')
            store = MobileEventStore(devices)
            store.enqueue({'type':'reminder','title':'Calendar reminder','message':'Meeting'},phone=phone['id'])
            first = store.events(phone['id'])['items'][0]
            snooze = store.snooze(phone['id'],'snooze-id-001',first['id'],600)
            self.assertEqual(store.snooze(phone['id'],'snooze-id-001',first['id'],600), snooze)
            with self.assertRaises(ValueError): store.snooze(other['id'],'snooze-id-other',first['id'],600)
            with self.assertRaises(ValueError): store.snooze(phone['id'],'snooze-id-001',first['id'],300)
            store.enqueue({'type':'task','title':'Task completed'},phone=phone['id'])
            immediate = store.events(phone['id'],first['sequence'])['items'][0]
            self.assertEqual(immediate['payload']['type'],'task')
            now[0] += 601
            later = store.events(phone['id'],immediate['sequence'])['items']
            self.assertEqual(len(later),1)
            self.assertEqual(later[0]['payload']['type'],'reminder')

    def test_real_service_account_jwt_signature_uses_pinned_crypto_without_network(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        with tempfile.TemporaryDirectory() as d:
            key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
            account = Path(d)/'account.json'
            account.write_text(json.dumps({'type':'service_account','project_id':'demo-project',
                'client_email':'sender@example.test','private_key':key.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()}))
            def request(url,body,headers):
                assertion=urllib_parse(body)['assertion'][0]
                unsigned,signature=assertion.rsplit('.',1)
                key.public_key().verify(base64.urlsafe_b64decode(signature+'='*(-len(signature)%4)),
                    unsigned.encode(),padding.PKCS1v15(),hashes.SHA256())
                return {'access_token':'local-fixture','expires_in':3600}
            provider=FcmPush({'service_account_file':str(account)},requester=request)
            self.assertEqual(provider.access(),'local-fixture')


def urllib_parse(value):
    from urllib.parse import parse_qs
    return parse_qs(value.decode())


if __name__ == '__main__': unittest.main()
