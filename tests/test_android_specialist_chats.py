"""Coach and Money chat rules and the worker chip wording, compiled with javac from the companion sources."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPANION = ROOT / 'apps/android/src/com/personalassistant/companion'


class SpecialistChatLogicTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_specialist_thread_and_worker_readiness(self):
        with tempfile.TemporaryDirectory() as output:
            sources = [COMPANION / 'SpecialistThread.java', COMPANION / 'WorkerReadiness.java',
                       ROOT / 'tests/jvm/SpecialistChatHarness.java']
            subprocess.run(['javac', '-encoding', 'UTF-8', '--release', '8', '-d', output, *map(str, sources)],
                           check=True, capture_output=True)
            run = subprocess.run(['java', '-Dfile.encoding=UTF-8', '-cp', output,
                                  'com.personalassistant.companion.SpecialistChatHarness'],
                                 capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('Specialist chats passed', run.stdout)

    def test_chats_share_the_timeline_and_never_gate_status_on_activity_focus(self):
        coach = (COMPANION / 'WorkoutCoach.java').read_text(encoding='utf-8')
        money = (COMPANION / 'MoneyConversation.java').read_text(encoding='utf-8')
        status = (COMPANION / 'AssistantStatus.java').read_text(encoding='utf-8')
        for source in (coach, money):
            self.assertIn('SpecialistChat.Timeline', source)
            self.assertIn('SpecialistThread.SENDING', source)
            self.assertIn('getDecorView().hasWindowFocus()', source)
            self.assertNotIn('a.hasWindowFocus()', source)
            self.assertNotIn('activity.hasWindowFocus()', source)
        # The first worker check runs on attach; focus only adds refreshes.
        self.assertIn('OnWindowFocusChangeListener', status)
        self.assertIn('WorkerReadiness.TIMEOUT', status)


if __name__ == '__main__':
    unittest.main()
