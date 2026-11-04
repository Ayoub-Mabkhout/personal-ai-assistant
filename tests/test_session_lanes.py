"""Independent context claims, bounded service slots and shared-session fences."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from personal_assistant.relay.api import create_app
from personal_assistant.relay.store import Queue,Conflict
from personal_assistant.orchestrator.runtime import execution_locks,InterruptedRun,write_json
from personal_assistant.orchestrator.service import AgentClient,AgentWorker,execution_slots
from personal_assistant.worker.runtime import TransportError


class SessionLaneTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.now=1900000000
        self.queue=Queue(self.root/'queue.sqlite3',clock=lambda:self.now,serial=True)
        self.queue.heartbeat('ready')

    def submit(self,identifier,root=None):
        payload={'id':identifier,'command':'A test instruction','timezone':'Europe/Berlin'}
        if root:payload['resume_task']={'root_id':root}
        return self.queue.submit(payload)[0]

    def claim(self):return self.queue.claim(30,session_lanes=True)

    def finish(self,job,session='worker-context'):
        return self.queue.finish(job['id'],job['lease_token'],'completed',
            {'summary':'Done','workers':[{'agent':'codex','session_id':session}]})

    def prepare(self,identifier,session=None):
        self.submit(identifier);self.finish(self.claim(),session or identifier+'-session')

    def test_followups_bypass_busy_general_lane_and_keep_context_order(self):
        self.prepare('root-one');self.prepare('root-two')
        self.submit('new-long-task');self.submit('next-new-task')
        self.submit('first-followup','root-one');self.submit('second-followup','root-one')
        self.submit('other-followup','root-two')
        general=self.claim();first=self.claim();other=self.claim()
        self.assertEqual([job['id'] for job in (general,first,other)],
            ['new-long-task','first-followup','other-followup'])
        self.assertIsNone(self.claim())
        self.finish(first)
        self.assertEqual(self.claim()['id'],'second-followup')

    def test_followup_waits_until_its_original_task_finishes(self):
        self.submit('root-one');self.submit('root-followup','root-one')
        original=self.claim();self.assertEqual(original['id'],'root-one')
        self.assertIsNone(self.claim())
        self.finish(original)
        self.assertEqual(self.claim()['id'],'root-followup')

    def test_old_roots_sharing_actual_session_do_not_run_together(self):
        self.prepare('root-one','shared-session');self.prepare('root-two','shared-session')
        self.submit('first-followup','root-one');self.submit('other-followup','root-two')
        first=self.claim();self.assertIsNone(self.claim())
        self.finish(first,'shared-session')
        self.assertEqual(self.claim()['id'],'other-followup')

    def test_latest_failed_result_does_not_hide_actual_session_alias(self):
        self.prepare('root-one','shared-session');self.prepare('root-two','shared-session')
        self.submit('failed-followup','root-one');job=self.claim()
        self.queue.finish(job['id'],job['lease_token'],'failed',{'summary':'Try again'})
        self.submit('first-followup','root-one');self.submit('other-followup','root-two')
        self.assertEqual(self.claim()['id'],'first-followup');self.assertIsNone(self.claim())

    def test_expired_lease_is_reclaimed_before_next_same_context(self):
        self.prepare('root-one');self.submit('first-followup','root-one');self.submit('second-followup','root-one')
        stale=self.claim();self.now+=31;self.queue.heartbeat('ready')
        retried=self.claim();self.assertEqual(retried['id'],stale['id'])
        self.assertNotEqual(retried['lease_token'],stale['lease_token'])
        with self.assertRaises(Conflict):self.finish(stale)
        self.assertIsNone(self.claim());self.finish(retried)
        self.assertEqual(self.claim()['id'],'second-followup')

    def test_cancelled_turn_releases_cloud_lane(self):
        self.prepare('root-one');self.submit('first-followup','root-one');self.submit('second-followup','root-one')
        first=self.claim();self.queue.cancel(first['id'])
        self.assertEqual(self.claim()['id'],'second-followup')

    def test_concurrent_claims_preserve_one_live_turn_per_session(self):
        self.prepare('root-one');self.prepare('root-two')
        for index in range(8):self.submit('followup-'+str(index),'root-one' if index%2 else 'root-two')
        with ThreadPoolExecutor(max_workers=6) as pool:jobs=list(pool.map(lambda _:self.claim(),range(6)))
        claimed=[job for job in jobs if job]
        self.assertEqual(len(claimed),2)
        self.assertEqual({job['payload']['resume_task']['root_id'] for job in claimed},{'root-one','root-two'})

    def test_legacy_claim_and_programmatic_queue_contracts_stay_unchanged(self):
        self.prepare('root-one');self.submit('new-long-task');self.submit('first-followup','root-one')
        self.assertIsNotNone(self.queue.claim());self.assertIsNone(self.queue.claim())
        normal=Queue(self.root/'normal.sqlite3',clock=lambda:self.now)
        normal.heartbeat('ready')
        for name in ('calendar-one','calendar-two'):
            normal.submit({'id':name,'command':'Show calendar','timezone':'UTC'})
        self.assertIsNotNone(normal.claim());self.assertIsNotNone(normal.claim())

    def test_agent_api_capability_opt_in_is_backward_compatible(self):
        with TestClient(create_app(self.root/'api.sqlite3','s'*48,'w'*48)) as client:
            worker={'Authorization':'Bearer '+'w'*48};owner={'Authorization':'Bearer '+'s'*48}
            client.post('/v1/agent/worker/heartbeat',headers=worker,json={'readiness':'ready'})
            for name in ('new-first','new-second'):
                self.assertEqual(client.post('/v1/agent/prompts',headers=owner,json={'id':name,'prompt':'Hi'}).status_code,201)
            response=client.post('/v1/agent/worker/claim',headers=worker,json={'session_lanes':True})
            self.assertTrue(response.json()['session_lanes']);self.assertEqual(response.json()['job']['id'],'new-first')
            self.assertIsNone(client.post('/v1/agent/worker/claim',headers=worker,json={}).json()['job'])
            self.assertEqual(client.post('/v1/worker/claim',headers=worker,json={'session_lanes':True}).status_code,422)

    def test_agent_client_falls_back_once_on_old_relay(self):
        class OldServer:
            def __init__(self):self.calls=[]
            def call(self,path,payload):
                self.calls.append((path,payload))
                if payload.get('session_lanes'):raise TransportError(422)
                return {'job':None}
        transport=OldServer();client=AgentClient(transport)
        client.call('/v1/worker/claim?wait=25',{'lease_seconds':120})
        client.call('/v1/worker/claim',{'lease_seconds':120})
        self.assertEqual(len(transport.calls),3);self.assertFalse(client.session_lanes)
        self.assertNotIn('session_lanes',transport.calls[-1][1])

    def test_local_locks_allow_independent_sessions_and_cancel_waiting_turn(self):
        first={'id':'followup-one','payload':{'resume_task':{'root_id':'root-one'}}}
        same={'id':'followup-two','payload':{'resume_task':{'root_id':'root-one'}}}
        other={'id':'followup-new','payload':{'resume_task':{'root_id':'root-two'}}}
        entered=threading.Event();cancel=threading.Event();errors=[]
        def wait_same():
            entered.set()
            try:
                with execution_locks(self.root,same,cancel):errors.append('unexpected acquisition')
            except InterruptedRun:errors.append('cancelled')
        with execution_locks(self.root,first,threading.Event()):
            with execution_locks(self.root,other,threading.Event()):pass
            thread=threading.Thread(target=wait_same);thread.start();self.assertTrue(entered.wait(1))
            cancel.set();thread.join(2);self.assertFalse(thread.is_alive())
        self.assertEqual(errors,['cancelled'])

    def test_local_alias_fence_covers_historical_shared_worker(self):
        for identifier in ('root-one','root-two'):
            folder=self.root/'jobs'/identifier;folder.mkdir(parents=True)
            write_json(folder/'job.json',{'workers':[{'agent':'codex','session_id':'shared-session'}]})
        first={'id':'followup-one','payload':{'resume_task':{'root_id':'root-one'}}}
        second={'id':'followup-two','payload':{'resume_task':{'root_id':'root-two'}}}
        cancel=threading.Event();entered=threading.Event();acquired=threading.Event();errors=[]
        def wait_alias():
            entered.set()
            try:
                with execution_locks(self.root,second,cancel):acquired.set()
            except InterruptedRun:errors.append('cancelled')
        with execution_locks(self.root,first,threading.Event()):
            thread=threading.Thread(target=wait_alias);thread.start();self.assertTrue(entered.wait(1))
            self.assertFalse(acquired.wait(.15));cancel.set();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,['cancelled'])

    def test_two_service_slots_execute_independent_contexts_and_keep_durable_outcomes(self):
        self.prepare('root-one');self.prepare('root-two')
        self.submit('first-followup','root-one');self.submit('other-followup','root-two')
        queue=self.queue;barrier=threading.Barrier(2);outbox=threading.Lock()
        class LocalServer:
            def call(self,path,payload=None):
                if path.endswith('/heartbeat'):return queue.heartbeat(payload['readiness'])
                if path.endswith('/claim'):return {'job':queue.claim(payload['lease_seconds'],session_lanes=payload.get('session_lanes',False))}
                identifier=path.split('/')[-2]
                if path.endswith('/result'):return queue.finish(identifier,payload['lease_token'],payload['state'],payload['result'])
                raise AssertionError(path)
        class Executor:
            def available(self):return True
            def execute(self,job,cancelled):
                barrier.wait(timeout=3)
                return {'state':'completed','result':{'summary':'Context answered'}}
        config={'runtime_dir':str(self.root/'worker'),'long_poll_seconds':0}
        workers=[AgentWorker(config,slot,outbox,client=AgentClient(LocalServer()),executor=Executor()) for slot in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(lambda worker:worker.tick(),workers)),[True,True])
        self.assertEqual(self.queue.get('first-followup')['state'],'completed')
        self.assertEqual(self.queue.get('other-followup')['state'],'completed')
        self.assertEqual(workers[0].ledger.pending(),[])
        self.assertTrue((self.root/'worker'/'status-slot-1.json').is_file())

    def test_slot_count_is_bounded(self):
        self.assertEqual(execution_slots({}),4)
        for invalid in (0,9,True,'4'):
            with self.subTest(value=invalid),self.assertRaises(ValueError):execution_slots({'agent_execution_slots':invalid})


if __name__=='__main__':unittest.main()
