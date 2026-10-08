import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from personal_assistant.orchestrator.runtime import CLI,Orchestrator,InterruptedRun,write_json


class FakeCLI:
    def __init__(self): self.calls=[]
    def run(self,prompt,directory,workspace,model,effort,cancelled,session=None,schema=None,instructions=None):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        self.calls.append({'model':model,'effort':effort,'session':session,'prompt':prompt,'instructions':instructions})
        if model=='gpt-6-luna' and schema:
            body=json.loads(prompt)
            if 'user_request' in body:
                output={'action':'dispatch','summary':'A worker will write the artifact.','tasks':[{
                    'model':'gpt-6.1-sol','effort':'medium','prompt':'Write artifact','workspace':str(workspace),
                    'resume_session':'','expected_artifacts':['artifact.txt'],'task_type':'general','skills':[]}]}
            else: output={'action':'complete','summary':'Artifact verified.','tasks':[]}
            identity='persistent-luna'
            text=json.dumps(output)
        else:
            (Path(workspace)/'artifact.txt').write_text('Worker output')
            identity=session or 'worker-'+directory.name;text='Artifact written.'
        result=directory/'result.txt';result.write_text(text,encoding='utf-8')
        return {'state':'completed','exit_code':0,'session_id':identity,'result':str(result),'trace':str(directory/'events.jsonl')}


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.fake=FakeCLI()
        self.agent=Orchestrator({'orchestrator_dir':str(self.root/'orchestrator'),'repository':str(self.root)},cli=self.fake)

    def tearDown(self): self.temp.cleanup()

    def job(self,identifier): return {'id':identifier,'payload':{'id':identifier,'command':'Write a report','timezone':'Europe/Berlin'}}

    def test_prompts_and_worker_results_resume_the_same_luna_session(self):
        for identifier in ['first-prompt','second-prompt']:
            result=self.agent.execute(self.job(identifier),threading.Event())
            self.assertEqual(result['state'],'completed')
            self.assertEqual(result['result']['orchestrator_session_id'],'persistent-luna')
            self.assertTrue(result['result']['workers'][0]['artifacts'][0]['exists'])
        luna=[call for call in self.fake.calls if call['model']=='gpt-6-luna']
        self.assertIsNone(luna[0]['session'])
        self.assertEqual([call['session'] for call in luna[1:]],['persistent-luna']*3)
        before=len(self.fake.calls)
        self.agent.execute(self.job('first-prompt'),threading.Event())
        self.assertEqual(len(self.fake.calls),before)

    def test_failed_or_interrupted_calls_are_not_blindly_replayed(self):
        directory=self.root/'unfinished';directory.mkdir()
        write_json(directory/'record.json',{'state':'running','session_id':'existing'})
        cli=CLI({'codex':'unused'})
        with patch('subprocess.Popen') as popen:
            with self.assertRaises(InterruptedRun):
                cli.run('prompt',directory,self.root,'gpt-6-luna','low',threading.Event())
            popen.assert_not_called()

    def test_completed_trace_recovers_crash_before_call_ack(self):
        directory=self.root/'finished';directory.mkdir()
        write_json(directory/'record.json',{'state':'running','session_id':None,'result':str(directory/'result.txt')})
        (directory/'events.jsonl').write_text(json.dumps({'type':'thread.started','thread_id':'recovered-session'})+'\n'+json.dumps({'type':'turn.completed'})+'\n')
        (directory/'result.txt').write_text('done')
        with patch('subprocess.Popen') as popen:
            result=CLI({'codex':'unused'}).run('prompt',directory,self.root,'gpt-6-luna','low',threading.Event())
            self.assertEqual(result['session_id'],'recovered-session')
            self.assertTrue(result['recovered']);popen.assert_not_called()

    def test_first_session_id_can_be_recovered_from_partial_trace(self):
        trace=self.agent.root/'jobs/first/dispatch-0/events.jsonl';trace.parent.mkdir(parents=True)
        trace.write_text(json.dumps({'type':'thread.started','thread_id':'recover-luna'})+'\n')
        self.assertEqual(self.agent.session()['session_id'],'recover-luna')

    def test_email_assignment_loads_skill_even_when_dispatcher_omits_its_name(self):
        skill=self.root/'skills/email/SKILL.md';skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: email\ndescription: Email retrieval\n---\nUse live Gmail and read full threads.')
        original=self.fake.run
        def classify(*args,**kwargs):
            record=original(*args,**kwargs)
            if kwargs.get('schema'):
                path=Path(record['result']);body=json.loads(path.read_text())
                if body['tasks']:
                    body['tasks'][0]['task_type']='email';body['tasks'][0]['skills']=[]
                    path.write_text(json.dumps(body))
            return record
        self.fake.run=classify
        result=self.agent.execute(self.job('email-task'),threading.Event())
        worker=result['result']['workers'][0]
        self.assertEqual(worker['skills'],['email'])
        self.assertIn('Use live Gmail and read full threads.',self.fake.calls[1]['instructions'])
        self.assertIn('dispatch_protocol',json.loads(self.fake.calls[0]['prompt']))

    def test_exact_identifiers_and_reply_context_reach_workers(self):
        job=self.job('followup-email')
        job['payload']['command']='Read owner.detail@example.com, not owner@example.com.'
        job['payload']['reply_context']={'parent_id':'parent-task','parent_summary':'Already sent the requested message.'}
        self.agent.execute(job,threading.Event())
        dispatcher=json.loads(self.fake.calls[0]['prompt'])
        self.assertEqual(dispatcher['followup_context'],job['payload']['reply_context'])
        instructions=self.fake.calls[1]['instructions']
        self.assertIn(job['payload']['command'],instructions)
        self.assertIn('Already sent the requested message.',instructions)
        self.assertIn('do not blindly replay',instructions)
