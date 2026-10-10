import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from personal_assistant.orchestrator.runtime import Orchestrator,write_json
from test_orchestrator import FakeCLI


class SessionCLI(FakeCLI):
    """FakeCLI with one fresh worker session per job and a scriptable first assignment."""
    def __init__(self):
        super().__init__();self.assignment={}

    def run(self,prompt,directory,workspace,model,effort,cancelled,session=None,schema=None,instructions=None):
        record=super().run(prompt,directory,workspace,model,effort,cancelled,session,schema,instructions)
        if schema and 'user_request' in json.loads(prompt) and self.assignment:
            path=Path(record['result']);body=json.loads(path.read_text(encoding='utf-8'))
            body['tasks'][0].update(self.assignment);path.write_text(json.dumps(body),encoding='utf-8')
        if not schema and not session:record['session_id']='session-'+Path(directory).parent.name
        return record


class RecentTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'claude.exe').write_text('')
        skill=self.root/'skills'/'documents'/'SKILL.md';skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: documents\ndescription: Document editing\n---\nEdit documents in place.',encoding='utf-8')
        self.luna=SessionCLI();self.claude=SessionCLI()
        # Temporary capacity sources: no real Codex logs, Claude installation or model call.
        self.config={'orchestrator_dir':str(self.root/'orchestrator'),'repository':str(self.root),
                     'codex_home':str(self.root),'claude':str(self.root/'claude.exe')}
        self.agent=Orchestrator(self.config,cli=self.luna,claude=self.claude)
        self.jobs=self.root/'orchestrator'/'jobs'

    def tearDown(self):self.temp.cleanup()

    def run_job(self,identifier,command='Write a report',age=None,**assignment):
        self.luna.assignment=assignment
        result=self.agent.execute({'id':identifier,'payload':{'id':identifier,'command':command,
                                   'created_at':'2026-10-09T08:00:00+00:00'}},threading.Event())
        if age is not None:
            stamp=time.time()-age;os.utime(self.jobs/identifier/'job.json',(stamp,stamp))
        return result

    def first_prompt(self,identifier):
        return next(json.loads(c['prompt']) for c in self.luna.calls if c['model']=='gpt-6-luna' and
                    json.loads(c['prompt']).get('task_id')==identifier and 'user_request' in json.loads(c['prompt']))

    def state(self,identifier):
        return json.loads((self.jobs/identifier/'job.json').read_text(encoding='utf-8'))

    def finished(self,identifier,session,age=0,command='Edit the quarterly report',outcome=None,**extra):
        directory=self.jobs/identifier;directory.mkdir(parents=True)
        state={'fingerprint':'fixture','request':{'id':identifier,'command':command},'phase':'finished',
               'workers':[{'agent':'codex','model':'gpt-6.1-sol','effort':'medium','session_id':session,
                           'workspace':str(self.root),'task_type':'documents','skills':['documents'],'result':'Done.'}],
               'outcome':outcome or {'state':'completed','result':{'summary':'Report edited.'}},**extra}
        write_json(directory/'job.json',state)
        stamp=time.time()-age;os.utime(directory/'job.json',(stamp,stamp))
        return directory

    def test_recent_tasks_describe_finished_sessions_newest_first(self):
        self.run_job('task-alpha-1','Draft the budget memo',age=120)
        self.run_job('task-bravo-2','Summarize the meeting notes',age=60,agent='claude',model='claude-sonnet-5-5',effort='high',
                     task_type='documents',skills=['documents'])
        self.run_job('task-charlie-3')
        recent=self.first_prompt('task-charlie-3')['recent_tasks']
        self.assertEqual([t['task_id'] for t in recent],['task-bravo-2','task-alpha-1'])
        bravo=recent[0]
        self.assertEqual(bravo['request'],'Summarize the meeting notes')
        self.assertEqual(bravo['outcome'],'completed');self.assertEqual(bravo['summary'],'Artifact verified.')
        self.assertEqual(bravo['created_at'],'2026-10-09T08:00:00+00:00');self.assertTrue(bravo['finished_at'])
        self.assertEqual(bravo['workers'],[{'session_id':'session-task-bravo-2','agent':'claude','model':'claude-sonnet-5-5',
            'effort':'high','workspace':str(self.agent.root),'task_type':'documents','skills':['documents']}])
        self.assertNotIn('persistent-luna',json.dumps(recent))
        # The current task is never its own recent task, and the snapshot is saved for recovery.
        self.assertEqual(self.state('task-charlie-3')['recent_tasks'],recent)
        self.assertIn('recent_tasks',self.first_prompt('task-charlie-3')['dispatch_protocol'])

    def test_recent_tasks_are_bounded_and_exclude_uncertain_sessions(self):
        self.finished('task-old-0001','s-old',age=8*86400)
        self.finished('mail-scan-0123456789abcdef01234567','s-mail')
        self.finished('task-failed-01','s-failed',outcome={'state':'needs_input','result':{'summary':'Interrupted.','reconciliation_required':True}})
        self.finished('task-asked-01','s-asked',age=50,outcome={'state':'needs_input','result':{'summary':'Which file?'}})
        self.finished('task-long-001','s-long',age=40,command='x'*5000)
        self.finished('task-dup-old1','s-dup',age=35)
        self.finished('task-dup-new1','s-dup',age=30,resumed_from_task=['task-dup-old1'])
        self.finished('task-taint-01','s-taint',age=20)
        # A newer resume of s-taint was interrupted, so its effects need reconciliation first.
        newer=self.finished('task-taint-02','s-other',age=10,outcome={'state':'needs_input','result':{'reconciliation_required':True}})
        (newer/'worker-0-0').mkdir();write_json(newer/'worker-0-0'/'record.json',{'state':'interrupted','session_id':'s-taint'})
        self.finished('task-luna-001','persistent-luna',age=5)
        write_json(self.agent.session_path,{'session_id':'persistent-luna'})
        recent=self.agent.recent_tasks('current-task')
        self.assertEqual([t['task_id'] for t in recent],['task-dup-new1','task-long-001','task-asked-01'])
        self.assertEqual(recent[0]['resumed_from_task'],['task-dup-old1'])
        self.assertLessEqual(len(recent[1]['request']),280);self.assertTrue(recent[1]['request'].endswith('...'))
        self.assertEqual(recent[2]['outcome'],'needs_input')
        limited=Orchestrator({**self.config,'recent_task_limit':2},cli=self.luna).recent_tasks('current-task')
        self.assertEqual([t['task_id'] for t in limited],['task-dup-new1','task-long-001'])
        budget=Orchestrator({**self.config,'recent_task_chars':700},cli=self.luna).recent_tasks('current-task')
        self.assertEqual([t['task_id'] for t in budget],['task-dup-new1'])
        self.assertEqual(Orchestrator({**self.config,'recent_task_days':0},cli=self.luna).recent_tasks('current-task'),[])

    def test_continuation_jobs_name_their_original_task(self):
        self.finished('task-root-001','s-root',age=30,command='Plan the garden layout')
        self.finished('continue-turn-1','s-root',age=10,command='Add a herb bed',
                      request={'id':'continue-turn-1','command':'Add a herb bed','resume_task':{'root_id':'task-root-001'}})
        recent=self.agent.recent_tasks('current-task')
        self.assertEqual(len(recent),1)
        self.assertEqual(recent[0]['continues_task'],'task-root-001')
        self.assertEqual(recent[0]['original_request'],'Plan the garden layout')

    def test_new_task_resumes_a_recent_session_and_records_its_origin(self):
        self.run_job('task-alpha-1','Draft the budget memo',age=60)
        result=self.run_job('task-bravo-2','Also add a travel section to it',resume_session='session-task-alpha-1')
        self.assertEqual(result['state'],'completed')
        worker_call=[c for c in self.luna.calls if c['model']=='gpt-6.1-sol'][-1]
        self.assertEqual(worker_call['session'],'session-task-alpha-1')
        self.assertIn('continues earlier task task-alpha-1',worker_call['instructions'])
        state=self.state('task-bravo-2')
        self.assertEqual(state['resumed_from_task'],['task-alpha-1'])
        self.assertEqual(state['workers'][0]['resumed_from_task'],'task-alpha-1')
        self.assertEqual(result['result']['workers'][0]['resumed_from_task'],'task-alpha-1')
        # The session is now listed once, at its newest task, with the link to the earlier one.
        self.run_job('task-charlie-3')
        recent=self.first_prompt('task-charlie-3')['recent_tasks']
        self.assertEqual([t['task_id'] for t in recent],['task-bravo-2'])
        self.assertEqual(recent[0]['resumed_from_task'],['task-alpha-1'])

    def test_claude_session_resumes_on_the_claude_worker(self):
        claude={'agent':'claude','model':'claude-opus-5-5','effort':'high'}
        self.run_job('task-alpha-1',age=60,**claude)
        result=self.run_job('task-bravo-2','Now tighten the wording',resume_session='session-task-alpha-1',**{**claude,'effort':'medium'})
        self.assertEqual(result['state'],'completed')
        self.assertEqual(self.claude.calls[-1]['session'],'session-task-alpha-1')
        self.assertEqual(self.state('task-bravo-2')['resumed_from_task'],['task-alpha-1'])

    def test_unknown_cross_agent_and_mismatched_resumes_are_rejected(self):
        self.run_job('task-alpha-1',age=60)
        other=self.root/'elsewhere';other.mkdir()
        cases={'task-guess-01':({'resume_session':'guessed-session'},'not in this task history or recent_tasks'),
               'task-agent-01':({'resume_session':'session-task-alpha-1','agent':'claude','model':'claude-opus-5-5'},'stays with the agent'),
               'task-model-01':({'resume_session':'session-task-alpha-1','model':'gpt-6-astra'},'original model'),
               'task-place-01':({'resume_session':'session-task-alpha-1','workspace':str(other)},'original workspace'),
               'task-skill-01':({'skills':['missing-skill']},'Unknown repository skill')}
        before=len(self.luna.calls)+len(self.claude.calls)
        for identifier,(assignment,message) in cases.items():
            result=self.run_job(identifier,**assignment)
            self.assertEqual(result['state'],'needs_input',identifier)
            self.assertIn(message,result['result']['summary'])
            self.assertTrue(result['result']['reconciliation_required'])
            self.assertNotIn('resumed_from_task',self.state(identifier))
        workers=[c for c in self.luna.calls[before:]+self.claude.calls if c['model']!='gpt-6-luna']
        self.assertEqual(workers,[])

    def test_rejected_assignment_starts_no_sibling_worker(self):
        self.run_job('task-alpha-1',age=60)
        original=self.luna.run
        def two(prompt,directory,workspace,model,effort,cancelled,session=None,schema=None,instructions=None):
            record=original(prompt,directory,workspace,model,effort,cancelled,session,schema,instructions)
            if schema and 'user_request' in json.loads(prompt):
                path=Path(record['result']);body=json.loads(path.read_text(encoding='utf-8'))
                body['tasks'].append({**body['tasks'][0],'resume_session':'guessed-session'})
                path.write_text(json.dumps(body),encoding='utf-8')
            return record
        self.luna.run=two
        before=len([c for c in self.luna.calls if c['model']!='gpt-6-luna'])
        self.assertEqual(self.run_job('task-pair-001')['state'],'needs_input')
        self.assertEqual(len([c for c in self.luna.calls if c['model']!='gpt-6-luna']),before)

    def plan(self,*workspaces,create=None):
        """Script Luna's first decision as one assignment per workspace; the first worker may create a folder."""
        original=self.luna.run
        def run(prompt,directory,workspace,model,effort,cancelled,session=None,schema=None,instructions=None):
            if not schema and create and prompt=='Assignment 0':create.mkdir(parents=True)
            record=original(prompt,directory,workspace,model,effort,cancelled,session,schema,instructions)
            if schema and 'user_request' in json.loads(prompt):
                path=Path(record['result']);body=json.loads(path.read_text(encoding='utf-8'));first=body['tasks'][0]
                body['tasks']=[{**first,'prompt':'Assignment '+str(index),'workspace':str(value)} for index,value in enumerate(workspaces)]
                path.write_text(json.dumps(body),encoding='utf-8')
            return record
        self.luna.run=run

    def worker_calls(self):return [c for c in self.luna.calls if c['model']!='gpt-6-luna']

    def test_a_later_assignment_may_use_a_folder_an_earlier_one_creates(self):
        project=self.root/'work'/'project'
        self.plan(self.root,project,create=project)
        result=self.run_job('task-mkdir-01','Create a project folder and build the site in it')
        self.assertEqual(result['state'],'completed')
        self.assertEqual([w['workspace'] for w in self.state('task-mkdir-01')['workers']],[str(self.root),str(project)])

    def test_a_missing_folder_stops_at_its_launch_and_keeps_earlier_results(self):
        self.plan(self.root,self.root/'never-created')
        result=self.run_job('task-gone-001')
        self.assertEqual(result['state'],'needs_input');self.assertTrue(result['result']['reconciliation_required'])
        self.assertIn('existing absolute directory',result['result']['summary'])
        self.assertEqual([c['prompt'] for c in self.worker_calls()],['Assignment 0'])
        self.assertEqual([w['workspace'] for w in self.state('task-gone-001')['workers']],[str(self.root)])
        # A relative workspace is still rejected before any worker of the decision starts.
        self.luna=SessionCLI();self.agent=Orchestrator(self.config,cli=self.luna,claude=self.claude)
        self.plan(self.root,'relative'+os.sep+'folder')
        result=self.run_job('task-relative-1')
        self.assertEqual(result['state'],'needs_input');self.assertIn('absolute directory',result['result']['summary'])
        self.assertEqual(self.worker_calls(),[])


if __name__=='__main__':unittest.main()
