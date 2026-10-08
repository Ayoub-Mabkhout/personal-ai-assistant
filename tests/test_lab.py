import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from personal_assistant import lab


@unittest.skipUnless(shutil.which('node'),'Node is needed for a local fake CLI; no model is called')
class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.workspace=self.root/'task'
        self.workspace.mkdir()
        (self.workspace/'environment.json').write_text('{}')
        self.cli=self.root/'fake-cli.js'
        self.patch=patch.object(lab,'default_root',return_value=self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_trace_retains_prompt_session_and_result(self):
        self.cli.write_text('const fs=require("fs");console.log(JSON.stringify({type:"thread.started",thread_id:"fake-session"}));'
            'process.stdin.resume();process.stdin.on("end",()=>{const i=process.argv.indexOf("--output-last-message");'
            'fs.writeFileSync(process.argv[i+1],"Local fake result");});')
        record=lab._run_coding_task(self.workspace,'Explicit test task',self.cli,shutil.which('node'),timeout=10)
        self.assertEqual(record['exit_code'],0)
        self.assertEqual(record['session_ids'],['fake-session'])
        self.assertEqual(Path(record['prompt']).read_text(),'Explicit test task')
        self.assertEqual(Path(record['result']).read_text(),'Local fake result')
        self.assertFalse(record['verified_effects'])

    def test_timeout_terminates_job_and_keeps_record(self):
        self.cli.write_text('process.stdin.resume();setInterval(()=>{},1000);')
        record=lab._run_coding_task(self.workspace,'Timeout test',self.cli,shutil.which('node'),timeout=0.3)
        self.assertEqual(record['error'],'timeout')
        self.assertIn(record['termination'],('process_tree','process_group'))
        saved=json.loads((Path(record['trace']).parent/'record.json').read_text())
        self.assertEqual(saved['error'],'timeout')

    def test_launch_uses_owner_authorized_full_computer_access(self):
        self.cli.write_text('const fs=require("fs");process.stdin.resume();process.stdin.on("end",()=>{'
            'const i=process.argv.indexOf("--output-last-message");fs.writeFileSync(process.argv[i+1],JSON.stringify(process.argv));});')
        record=lab._run_coding_task(self.workspace,'Check launch configuration',self.cli,shutil.which('node'),timeout=10)
        args=json.loads(Path(record['result']).read_text())
        self.assertIn('--ignore-user-config',args)
        self.assertEqual(args[args.index('--sandbox')+1],'danger-full-access')
        self.assertIn('approval_policy="never"',args)
        self.assertNotIn('windows.sandbox="elevated"',args)
