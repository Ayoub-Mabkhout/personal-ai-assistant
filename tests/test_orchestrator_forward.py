import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import tempfile
import threading
import unittest
import uuid
from personal_assistant.orchestrator import forwarding
from personal_assistant.orchestrator.runtime import Decision,Orchestrator,write_json
from test_orchestrator import FakeCLI

TOKEN='fixture-bridge-token-0123456789abcdef'


class FakeBridge:
    """Local stand-in for the coordination bridge: same validation, idempotent message IDs."""
    def __init__(self):
        self.posts=[];self.stored={};self.status='transmitted';self.reject=None
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def answer(self,code,data):
                encoded=json.dumps(data).encode();self.send_response(code)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)))
                self.end_headers();self.wfile.write(encoded)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                bridge.posts.append({'headers':dict(self.headers),'body':body})
                if self.headers.get('Authorization')!='Bearer '+TOKEN:return self.answer(401,{'error':'Local channel token required'})
                if bridge.reject:return self.answer(bridge.reject,{'error':'Sender not allowed'})
                if body.get('from')=='luna' and not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',str(body.get('task',''))):
                    return self.answer(400,{'error':'Luna messages also need their task ID'})
                if body['to'] not in ('claude','codex') or not body['text'].strip() or len(body['text'])>12000:
                    return self.answer(400,{'error':'Invalid message'})
                if body['id'] in bridge.stored:return self.answer(200,bridge.stored[body['id']])
                message={**body,'created':'2026-10-09T12:00:00Z','status':bridge.status,
                         **({'error':'Claude desktop session is offline'} if bridge.status=='queued' else {})}
                bridge.stored[body['id']]=message;self.answer(201,message)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.port=self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever,daemon=True).start()

    def close(self):self.server.shutdown();self.server.server_close()


class ScriptedLuna(FakeCLI):
    """FakeCLI whose first dispatcher decision is replaced by a scripted one."""
    def __init__(self):super().__init__();self.decision=None
    def run(self,prompt,directory,workspace,model,effort,cancelled,session=None,schema=None,instructions=None):
        record=super().run(prompt,directory,workspace,model,effort,cancelled,session,schema,instructions)
        if schema and 'user_request' in json.loads(prompt) and self.decision is not None:
            Path(record['result']).write_text(json.dumps(self.decision),encoding='utf-8')
        return record


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.bridge=FakeBridge()
        self.coordination=self.root/'coordination'/'config.json';self.coordination.parent.mkdir()
        self.write_bridge_config(self.bridge.port)
        (self.root/'claude.exe').write_text('')
        # Temporary capacity and bridge sources: no real sessions, bridge or model call.
        self.config={'orchestrator_dir':str(self.root/'orchestrator'),'repository':str(self.root),'codex_home':str(self.root),
                     'claude':str(self.root/'claude.exe'),'coordination_config':str(self.coordination)}
        self.luna=ScriptedLuna();self.agent=Orchestrator(self.config,cli=self.luna)

    def tearDown(self):self.bridge.close();self.temp.cleanup()

    def write_bridge_config(self,port):
        write_json(self.coordination,{'port':port,'token':TOKEN,'codexSession':'codex-session-fixture','claudeSession':'claude-session-fixture'})

    def job(self,identifier,command='Fix the Companion crash when Reply is tapped.',**extra):
        return {'id':identifier,'payload':{'id':identifier,'command':command,'timezone':'Europe/Berlin',
                                           'created_at':'2026-10-09T08:00:00+00:00',**extra}}

    def forward(self,identifier,target='claude',**job):
        self.luna.decision={'action':'forward','summary':'Companion app bug; routed by capacity.','forward_to':target,'tasks':[]}
        return self.agent.execute(self.job(identifier,**job),threading.Event())

    def stored_job(self,identifier):
        return (self.root/'orchestrator'/'jobs'/identifier/'job.json').read_text(encoding='utf-8')

    def workers(self):return [c for c in self.luna.calls if c['model']!='gpt-6-luna']

    def test_forwards_the_verbatim_request_to_each_session(self):
        command='Fix the Companion crash when "Reply" is tapped.\n  Keep  this spacing\tand ünïcode ✓'
        context={'parent_id':'parent-task-1','parent_summary':'Crash reproduced.'}
        for target in ('claude','codex'):
            identifier='dev-task-'+target
            result=self.forward(identifier,target,command=command,reply_context=context)
            self.assertEqual(result['state'],'completed')
            expected=str(uuid.uuid5(forwarding.NAMESPACE,'luna-forward:'+identifier))
            self.assertEqual(result['result']['forward_message_id'],expected)
            self.assertIn('Forwarded to the '+forwarding.SESSIONS[target]+' (message '+expected+', transmitted).',result['result']['summary'])
            self.assertIn('routed by capacity',result['result']['summary'])
            post=self.bridge.posts[-1]
            body=post['body']
            self.assertEqual((body['id'],body['from'],body['to'],body['task']),(expected,'luna',target,identifier))
            self.assertTrue(body['topic'].startswith('Forwarded development task'));self.assertLessEqual(len(body['topic']),120)
            text=body['text']
            self.assertIn(forwarding.BEGIN+'\n'+command+'\n'+forwarding.END,text)
            self.assertIn('\nRequest SHA-256: '+hashlib.sha256(command.encode('utf-8')).hexdigest()+'\n',text)
            self.assertIn('Requested at: 2026-10-09T08:00:00+00:00 (Europe/Berlin)',text)
            self.assertIn('Crash reproduced.',text)
            self.assertIn('report the results directly to the owner',text)
            self.assertEqual(post['headers']['Authorization'],'Bearer '+TOKEN)
            self.assertEqual(post['headers']['Host'],'127.0.0.1:'+str(self.bridge.port))
            stored=self.stored_job(identifier)
            self.assertNotIn(TOKEN,stored);self.assertNotIn('session-fixture',stored)
            record=json.loads(stored)['forward']
            self.assertEqual((record['message_id'],record['state'],record['bridge']['status']),(expected,'answered','transmitted'))
        self.assertEqual(self.workers(),[])
        prompt=json.loads(self.luna.calls[0]['prompt'])
        self.assertEqual(prompt['dev_forwarding'],{'available':True,'sessions':['claude','codex']})
        self.assertIn('forward_to',prompt['dispatch_protocol'])

    def test_a_rerun_reuses_the_same_message_id(self):
        self.assertEqual(self.forward('dev-retry-01')['state'],'completed')
        # Crash after the bridge stored the message but before the outcome was saved.
        path=self.root/'orchestrator'/'jobs'/'dev-retry-01'/'job.json'
        state=json.loads(path.read_text(encoding='utf-8'));state.pop('outcome');write_json(path,state)
        result=Orchestrator(self.config,cli=self.luna).execute(self.job('dev-retry-01'),threading.Event())
        self.assertEqual(result['state'],'completed')
        self.assertEqual(len({p['body']['id'] for p in self.bridge.posts}),1)
        self.assertEqual((len(self.bridge.posts),len(self.bridge.stored)),(2,1))
        Orchestrator(self.config,cli=self.luna).execute(self.job('dev-retry-01'),threading.Event())
        self.assertEqual(len(self.bridge.posts),2)

    def test_an_offline_session_stays_queued_at_the_bridge(self):
        self.bridge.status='queued'
        result=self.forward('dev-queued-1')
        self.assertEqual(result['state'],'completed')
        self.assertIn('queued',result['result']['summary']);self.assertIn('Claude desktop session is offline',result['result']['summary'])

    def test_bridge_failures_need_input_and_are_never_dropped(self):
        def closed_port():
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));return probe.getsockname()[1]
        cases=[('dev-reject-1',lambda:setattr(self.bridge,'reject',403),'HTTP 403','failed'),
               ('dev-uncertain',lambda:(setattr(self.bridge,'reject',None),setattr(self.bridge,'status','uncertain')),'as uncertain','answered'),
               ('dev-offline-1',lambda:self.write_bridge_config(closed_port()),'unreachable','failed'),
               ('dev-missing-1',lambda:self.coordination.unlink(),'not configured','failed'),
               ('short',lambda:None,'cannot be forwarded','failed')]
        for identifier,prepare,message,state in cases:
            prepare()
            result=self.forward(identifier)
            self.assertEqual(result['state'],'needs_input',identifier)
            self.assertIn(message,result['result']['summary'])
            self.assertIn(forwarding.message_id(identifier),result['result']['summary'])
            self.assertTrue(result['result']['reconciliation_required'])
            stored=self.stored_job(identifier);self.assertNotIn(TOKEN,stored)
            self.assertEqual(json.loads(stored)['forward']['state'],state)
        self.assertEqual(self.workers(),[])

    def test_forward_fields_must_be_consistent(self):
        assignment={'agent':'codex','model':'gpt-6.1-sol','effort':'medium','prompt':'Fix it','workspace':str(self.root),
                    'resume_session':'','expected_artifacts':[],'task_type':'coding','skills':[]}
        decisions={'dev-none-001':{'action':'forward','forward_to':'none','tasks':[]},
                   'dev-tasks-01':{'action':'forward','forward_to':'claude','tasks':[assignment]},
                   'dev-done-001':{'action':'complete','forward_to':'claude','tasks':[]},
                   'dev-split-01':{'action':'dispatch','forward_to':'codex','tasks':[assignment]}}
        for identifier,decision in decisions.items():
            self.luna.decision={'summary':'Routing.',**decision}
            result=self.agent.execute(self.job(identifier),threading.Event())
            self.assertEqual(result['state'],'needs_input',identifier)
            self.assertTrue(result['result']['reconciliation_required'])
        self.assertEqual(self.bridge.posts,[]);self.assertEqual(self.workers(),[])

    def test_schema_requires_every_field_including_the_forward_target(self):
        schema=Decision.model_json_schema()
        self.assertEqual(set(schema['required']),set(schema['properties']))
        self.assertEqual(schema['properties']['forward_to']['enum'],['none','claude','codex'])
        self.assertIn('forward',schema['properties']['action']['enum'])

    def test_ordinary_decisions_never_touch_the_bridge(self):
        result=self.agent.execute(self.job('ordinary-01',command='Write a report'),threading.Event())
        self.assertEqual(result['state'],'completed');self.assertEqual(len(self.workers()),1)
        self.assertEqual(self.bridge.posts,[])
        self.assertNotIn('forward',json.loads(self.stored_job('ordinary-01')))

    def test_an_oversized_request_keeps_its_full_digest(self):
        command='x'*13000
        body=forwarding.message({},self.job('dev-large-01',command=command),'codex','Routing.')
        self.assertLessEqual(forwarding.js_length(body['text']),forwarding.TEXT_LIMIT)
        self.assertIn('Request SHA-256: '+forwarding.request_digest(command),body['text'])
        self.assertIn('complete request is stored with queue task dev-large-01',body['text'])
        self.assertEqual(body['from'],'luna')
        self.assertEqual(forwarding.message({'dev_forward_sender':'relay'},self.job('dev-large-01'),'codex','Routing.')['from'],'relay')


if __name__=='__main__':unittest.main()
