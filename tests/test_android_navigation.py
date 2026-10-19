"""Exercise actual tab history, including restored and direct-entry navigation."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AndroidNavigationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_page_history(self):
        with tempfile.TemporaryDirectory() as output:
            sources = [ROOT / 'apps/android/src/com/personalassistant/companion/PageHistory.java',
                       ROOT / 'tests/jvm/PageHistoryHarness.java']
            subprocess.run(['javac', '--release', '8', '-d', output, *map(str, sources)], check=True, capture_output=True)
            run = subprocess.run(['java', '-cp', output, 'com.personalassistant.companion.PageHistoryHarness'], check=True, capture_output=True, text=True)
            self.assertIn('Page history passed', run.stdout)
