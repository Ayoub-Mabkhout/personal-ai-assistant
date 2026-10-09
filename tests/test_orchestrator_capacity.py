import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from personal_assistant.orchestrator import capacity
from personal_assistant.orchestrator.runtime import Orchestrator
from test_orchestrator import FakeCLI

NOW=1_800_000_000


def record(stamp,limit_id='codex',five=(10.0,NOW+3600),week=(60.0,NOW+86400),reached=None):
    windows={'primary':{'used_percent':five[0],'window_minutes':300,'resets_at':five[1]},
             'secondary':{'used_percent':week[0],'window_minutes':10080,'resets_at':week[1]}} if five else {'primary':None,'secondary':None}
    return json.dumps({'timestamp':stamp,'type':'event_msg','payload':{'type':'token_count','info':{},
        'rate_limits':{'limit_id':limit_id,**windows,'plan_type':'plus','rate_limit_reached_type':reached}}})


def claude_event(five=.25,week=.5,status='allowed'):
    return {'type':'rate_limit_event','rate_limit_info':{'status':status,'rateLimitType':'five_hour',
            'unifiedWindows':{'five_hour':{'utilization':five,'resetsAt':NOW+1800},'seven_day':{'utilization':week,'resetsAt':NOW+7200}}}}


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.day=self.home/'sessions'/'2026'/'10'/'09';self.day.mkdir(parents=True)
        # No real Claude installation or background model call in tests.
        self.config={'codex_home':str(self.home),'orchestrator_dir':str(self.home/'orchestrator'),'claude':str(self.home/'claude.exe')}
        (self.home/'claude.exe').write_text('')

    def tearDown(self):self.temp.cleanup()

    def rollout(self,name,lines,age=0):
        path=self.day/('rollout-'+name+'.jsonl');path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        os.utime(path,(time.time()-age,time.time()-age));return path

    def test_newest_codex_record_across_sessions_is_reported(self):
        self.rollout('old',[record('2026-10-09T10:00:00Z',five=(80.0,NOW+600))],age=60)
        self.rollout('new',['{"partial',record('2026-10-09T11:00:00Z',five=(12.0,NOW+1200)),'{"type":"other"}'])
        codex=capacity.snapshot(self.config,now=NOW)['codex']
        self.assertTrue(codex['available'])
        self.assertEqual(codex['five_hour'],{'used_percent':12.0,'remaining_percent':88.0,'resets_in_minutes':20,'resets_at':'2027-01-15T08:20:00+00:00'})
        self.assertEqual(codex['weekly']['remaining_percent'],40.0)

    def test_reset_window_reads_as_unused_and_placeholder_limits_are_ignored(self):
        self.rollout('a',[record('2026-10-09T11:00:00Z',five=(95.0,NOW-60)),record('2026-10-09T11:00:01Z',limit_id='premium',five=None)])
        codex=capacity.snapshot(self.config,now=NOW)['codex']
        self.assertEqual(codex['five_hour']['used_percent'],0.0)
        self.assertTrue(codex['five_hour']['reset_since_observed'])

    def test_claude_figures_come_from_worker_runs(self):
        self.assertFalse(capacity.snapshot(self.config,now=NOW)['claude']['available'])
        capacity.save_claude(self.config,[{'type':'system'},claude_event(five=.9,status='allowed_warning')],now=NOW-120)
        claude=capacity.snapshot(self.config,now=NOW)['claude']
        self.assertEqual(claude['five_hour']['used_percent'],90.0)
        self.assertEqual(claude['five_hour']['remaining_percent'],10.0)
        self.assertEqual(claude['weekly']['remaining_percent'],50.0)
        self.assertEqual(claude['observed_minutes_ago'],2)
        self.assertIsNone(claude['limit_reached'])
        capacity.save_claude(self.config,[claude_event(five=1.0,status='rejected')],now=NOW)
        self.assertEqual(capacity.snapshot(self.config,now=NOW)['claude']['limit_reached'],'five_hour')

    def test_stale_claude_figures_refresh_in_the_background_only_when_enabled(self):
        with patch('threading.Thread') as thread:
            capacity.snapshot(self.config,now=NOW)
            thread.assert_not_called()
            capacity.snapshot({**self.config,'claude_capacity_refresh':True},now=NOW)
            thread.assert_called_once()

    def test_missing_sources_never_break_dispatch(self):
        result=capacity.snapshot({'codex_home':str(self.home/'absent'),'orchestrator_dir':str(self.home/'o'),'claude':str(self.home/'missing')})
        self.assertFalse(result['codex']['available']);self.assertFalse(result['claude']['available'])

    def test_every_dispatcher_turn_receives_capacity(self):
        self.rollout('a',[record('2026-10-09T11:00:00Z')])
        fake=FakeCLI()
        agent=Orchestrator({**self.config,'repository':str(self.home)},cli=fake)
        job={'id':'capacity-job','payload':{'id':'capacity-job','command':'Write a report'}}
        self.assertEqual(agent.execute(job,threading.Event())['state'],'completed')
        luna=[json.loads(call['prompt']) for call in fake.calls if call['model']=='gpt-6-luna']
        self.assertEqual(len(luna),2)
        for prompt in luna:self.assertTrue(prompt['agent_capacity']['codex']['available'])
        self.assertIn('agent_capacity',luna[0]['dispatch_protocol'])


class ClaudeRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.luna=FakeCLI();self.claude=FakeCLI()
        self.agent=Orchestrator({'orchestrator_dir':str(self.root/'orchestrator'),'repository':str(self.root),'codex_home':str(self.root)},cli=self.luna,claude=self.claude)

    def tearDown(self):self.temp.cleanup()

    def dispatch(self,assignment):
        original=self.luna.run
        def run(prompt,directory,workspace,model,effort,cancelled,session=None,schema=None,instructions=None):
            if schema and 'user_request' in json.loads(prompt):
                directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
                (directory/'result.txt').write_text(json.dumps({'action':'dispatch','summary':'Delegating.','tasks':[{
                    'prompt':'Write artifact','workspace':str(workspace),'resume_session':'','expected_artifacts':['artifact.txt'],
                    'task_type':'general','skills':[],**assignment}]}),encoding='utf-8')
                self.luna.calls.append({'model':model})
                return {'state':'completed','session_id':'persistent-luna','result':str(directory/'result.txt'),'trace':str(directory/'events.jsonl')}
            return original(prompt,directory,workspace,model,effort,cancelled,session,schema,instructions)
        self.luna.run=run
        return self.agent.execute({'id':'route-job','payload':{'id':'route-job','command':'Write a report'}},threading.Event())

    def test_claude_assignments_run_on_the_claude_worker(self):
        result=self.dispatch({'agent':'claude','model':'claude-sonnet-5-5','effort':'high'})
        self.assertEqual(result['state'],'completed')
        self.assertEqual([c['model'] for c in self.claude.calls],['claude-sonnet-5-5'])
        self.assertEqual(result['result']['workers'][0]['agent'],'claude')
        self.assertFalse(any(c['model']=='claude-sonnet-5-5' for c in self.luna.calls))

    def test_model_must_belong_to_its_agent(self):
        for assignment in ({'agent':'claude','model':'gpt-6-sol','effort':'low'},{'agent':'codex','model':'claude-opus-5-5','effort':'low'},
                           {'agent':'claude','model':'claude-opus-5-5','effort':'ultra'}):
            self.temp.cleanup();self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.setUp()
            result=self.dispatch(assignment)
            self.assertEqual(result['state'],'needs_input')
            self.assertEqual(self.claude.calls,[])


if __name__=='__main__':unittest.main()
