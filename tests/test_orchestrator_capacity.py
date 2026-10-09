import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from personal_assistant.orchestrator import capacity
from personal_assistant.orchestrator.runtime import Orchestrator
from test_orchestrator import FakeCLI

NOW=1_800_000_000


def record(stamp,limit_id='codex',five=(10.0,NOW+3600),week=(60.0,NOW+86400),reached=None):
    windows={'primary':{'used_percent':five[0],'window_minutes':300,'resets_at':five[1]},
             'secondary':{'used_percent':week[0],'window_minutes':10080,'resets_at':week[1]}} if five else {'primary':None,'secondary':None}
    return json.dumps({'timestamp':stamp,'type':'event_msg','payload':{'type':'token_count','info':{},
        'rate_limits':{'limit_id':limit_id,**windows,'plan_type':'plus','rate_limit_reached_type':reached}}})


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.day=self.home/'sessions'/'2026'/'10'/'09';self.day.mkdir(parents=True)

    def tearDown(self):self.temp.cleanup()

    def rollout(self,name,lines,age=0):
        path=self.day/('rollout-'+name+'.jsonl');path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        os.utime(path,(time.time()-age,time.time()-age));return path

    def test_newest_record_across_sessions_is_reported(self):
        self.rollout('old',[record('2026-10-09T10:00:00Z',five=(80.0,NOW+600))],age=60)
        self.rollout('new',['{"partial',record('2026-10-09T11:00:00Z',five=(12.0,NOW+1200)),'{"type":"other"}'])
        result=capacity.snapshot({'codex_home':str(self.home)},now=NOW)
        codex=result['limits']['codex']
        self.assertTrue(result['available'])
        self.assertEqual(codex['five_hour']['used_percent'],12.0)
        self.assertEqual(codex['five_hour']['remaining_percent'],88.0)
        self.assertEqual(codex['five_hour']['resets_in_minutes'],20)
        self.assertEqual(codex['weekly']['remaining_percent'],40.0)

    def test_window_that_has_reset_reads_as_unused_and_placeholders_are_skipped(self):
        self.rollout('a',[record('2026-10-09T11:00:00Z',five=(95.0,NOW-60)),record('2026-10-09T11:00:01Z',limit_id='premium',five=None)])
        result=capacity.snapshot({'codex_home':str(self.home)},now=NOW)
        self.assertEqual(result['limits']['codex']['five_hour'],{'used_percent':0.0,'remaining_percent':100.0,'resets_in_minutes':None,
            'resets_at':'2027-01-15T07:59:00+00:00','reset_since_observed':True})
        self.assertNotIn('premium',result['limits'])

    def test_missing_logs_never_break_dispatch(self):
        self.assertFalse(capacity.snapshot({'codex_home':str(self.home/'absent')})['available'])

    def test_every_dispatcher_turn_receives_capacity(self):
        self.rollout('a',[record('2026-10-09T11:00:00Z')])
        fake=FakeCLI()
        agent=Orchestrator({'orchestrator_dir':str(self.home/'orchestrator'),'repository':str(self.home),'codex_home':str(self.home)},cli=fake)
        job={'id':'capacity-job','payload':{'id':'capacity-job','command':'Write a report'}}
        self.assertEqual(agent.execute(job,threading.Event())['state'],'completed')
        luna=[json.loads(call['prompt']) for call in fake.calls if call['model']=='gpt-6-luna']
        self.assertEqual(len(luna),2)
        for prompt in luna:self.assertTrue(prompt['agent_capacity']['available'])
        self.assertIn('agent_capacity',luna[0]['dispatch_protocol'])


if __name__=='__main__':unittest.main()
