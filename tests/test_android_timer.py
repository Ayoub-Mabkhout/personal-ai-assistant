"""Compile the real deterministic timer parser: no Android, network or paid speech."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
class TimerParserTests(unittest.TestCase):
    def test_durations_and_safe_rejections(self):
        cases = {
            'Hey Chat set a timer for 5 minutes': 300,
            'hey chat, set a timer for an hour.': 3600,
            'start a timer for two hours': 7200,
            'Please set me a timer for twenty-five minutes!': 1500,
            'Could you set a timer for one hour and thirty minutes please?': 5400,
            'set a timer for 1 hour 2 minutes 3 seconds': 3723,
            'set a timer for half an hour': 1800,
            'set a timer for a quarter of an hour': 900,
            'set a timer for 1.5 hours': 5400,
            'set a timer for one and a half hours': 5400,
            'set a timer for 24 hours': 86400,
            'set a timer for one hundred and twenty minutes': 7200,
            'set a timer for 25 hours': 0,
            'set a timer for zero minutes': 0,
            'set a timer for -5 minutes': 0,
            'set a timer for 0.1 seconds': 0,
            'set a timer for 9999999999999999999999 minutes': 0,
            'set a timer for five': 0,
            'set a timer': 0,
            'set a timer for five minutes and email me': 0,
            'set a timer for twenty thirty minutes': 0,
            'set a timer for one two minutes': 0,
            'explain how to set a timer for five minutes': None,
            'cancel the timer': None,
            'set an alarm for 5 minutes': None,
        }
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run(['javac', '-encoding', 'UTF-8', '--release', '8', '-d', folder,
                str(ROOT / 'apps/android/src/com/personalassistant/companion/TimerCommand.java'),
                str(ROOT / 'apps/android/src/com/personalassistant/companion/CaptureTurnPolicy.java'),
                str(ROOT / 'tests/jvm/TimerHarness.java')], check=True, capture_output=True)
            result = subprocess.run(['java', '-cp', folder, 'com.personalassistant.companion.TimerHarness'],
                input='\n'.join(cases) + '\n', text=True, capture_output=True, check=True)
            values = result.stdout.splitlines()
            self.assertEqual(len(values), len(cases))
            for (phrase, expected), actual in zip(cases.items(), values):
                with self.subTest(phrase=phrase):
                    self.assertEqual(actual, 'null' if expected is None else str(expected))

    def test_wake_wait_and_short_command_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run(['javac', '--release', '8', '-d', folder,
                str(ROOT / 'apps/android/src/com/personalassistant/companion/TimerCommand.java'),
                str(ROOT / 'apps/android/src/com/personalassistant/companion/CaptureTurnPolicy.java'),
                str(ROOT / 'tests/jvm/TimerHarness.java')], check=True, capture_output=True)
            cases = {'gate:19200,0,19200,true': 'false', 'gate:32000,0,32000,true': 'false',
                'gate:48000,4800,19200,true': 'false', 'gate:80000,4800,32000,true': 'true',
                'gate:32000,12800,19200,true': 'true', 'gate:21600,2400,19200,false': 'true'}
            result = subprocess.run(['java', '-cp', folder, 'com.personalassistant.companion.TimerHarness'],
                input='\n'.join(cases)+'\n', text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.splitlines(), list(cases.values()))
