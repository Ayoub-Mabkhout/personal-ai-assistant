"""Hey Chat battery-use arithmetic (BatteryUsage.java), compiled with javac and driven through tests/jvm/BatteryUsageProbe.java.

Synthetic samples only: a 3700 mAh battery whose whole-percent level follows the charge counter. Skipped where no JDK
is installed."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / 'apps/android/src/com/personalassistant/companion/BatteryUsage.java', ROOT / 'tests/jvm/BatteryUsageProbe.java']
MAIN = 'com.personalassistant.companion.BatteryUsageProbe'
OFF, LISTENING, OTHER = 0, 1, 2
CAPACITY_UAH = 3_700_000
WALL0, ELAPSED0 = 1_800_000_000_000, 50_000_000


def tool(name):
    found = shutil.which(name)
    home = os.environ.get('JAVA_HOME')
    if not found and home:
        candidate = Path(home) / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
        found = str(candidate) if candidate.is_file() else None
    return found


JAVAC, JAVA = tool('javac'), tool('java')
BUILD = None


def setUpModule():
    global BUILD
    if not (JAVAC and JAVA):
        return
    BUILD = tempfile.TemporaryDirectory(prefix='assistant-battery-jvm-')
    for flags in (['--release', '8'], []):
        built = subprocess.run([JAVAC, '-encoding', 'UTF-8', *flags, '-d', BUILD.name, *map(str, SOURCES)], capture_output=True, text=True)
        if built.returncode == 0:
            return
    raise RuntimeError(built.stderr)


def tearDownModule():
    if BUILD:
        BUILD.cleanup()


def probe(lines):
    run = subprocess.run([JAVA, '-Dfile.encoding=UTF-8', '-cp', BUILD.name, MAIN], input='\n'.join(lines) + '\n', capture_output=True, text=True, encoding='utf-8', check=True)
    return run.stdout.splitlines()


class Phone:
    """Synthetic phone: a clock, a draining charge counter and the state each sample records."""

    def __init__(self, counter=True):
        self.ms, self.up, self.charge, self.counter, self.rows, self.wakes = 0, 0, int(CAPACITY_UAH * .9), counter, [], 0
        self.boot = 0

    def line(self, mode, screen, plugged=False):
        level = round(self.charge * 100 / CAPACITY_UAH)
        return '\t'.join(map(str, (WALL0 + self.ms, ELAPSED0 + self.ms - self.boot, self.up, level, self.charge if self.counter else 0,
                                   int(plugged), int(screen), mode, self.wakes)))

    def stretch(self, mode, screen, hours, mah_per_hour, awake=None, plugged=False, step=15):
        """Samples every `step` minutes for `hours`, starting one minute after the previous stretch."""
        awake = (1.0 if mode != OFF or screen else .05) if awake is None else awake
        self.advance(1, mah_per_hour, awake, plugged)
        self.rows.append(self.line(mode, screen, plugged))
        for _ in range(round(hours * 60 / step)):
            self.advance(step, mah_per_hour, awake, plugged)
            self.rows.append(self.line(mode, screen, plugged))
        return self

    def advance(self, minutes, mah_per_hour, awake, plugged):
        self.ms += minutes * 60000
        self.up += round(minutes * 60000 * awake)
        self.charge = min(CAPACITY_UAH, self.charge + 3000 * minutes * 60) if plugged else self.charge - round(mah_per_hour * 1000 * minutes / 60)

    def report(self):
        fields = probe(self.rows + ['end'])[0].split('\t')
        keys = ('samples', 'idle_ms', 'active_ms', 'baseline_ms', 'idle_drop', 'baseline_drop', 'skipped', 'cost', 'cost_mah', 'capacity', 'confidence', 'summary', 'headline')
        out = dict(zip(keys, fields))
        for key in keys[:7]:
            out[key] = int(out[key])
        for key in ('cost', 'cost_mah', 'capacity'):
            out[key] = float(out[key])
        return out


HOUR = 3600000


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class BatteryUsageTests(unittest.TestCase):
    def test_intervals_are_split_by_listener_and_screen_state(self):
        r = (Phone().stretch(LISTENING, False, 3, 40).stretch(LISTENING, True, 1, 400).stretch(LISTENING, False, 1, 40)
             .stretch(OFF, False, 2, 15).report())
        self.assertEqual((r['idle_ms'], r['active_ms'], r['baseline_ms']), (4 * HOUR, HOUR, 2 * HOUR))
        self.assertEqual(r['skipped'], 3)  # each state change leaves its one boundary interval out

    def test_charging_is_never_counted(self):
        phone = Phone().stretch(LISTENING, False, 2, 40).stretch(LISTENING, False, 1, 0, plugged=True).stretch(LISTENING, False, 2, 40)
        r = phone.report()
        self.assertEqual((r['idle_ms'], r['skipped']), (4 * HOUR, 6))
        self.assertTrue(2 <= r['idle_drop'] <= 6, r['idle_drop'])

    def test_a_charge_between_two_unplugged_samples_is_left_out(self):
        phone = Phone()
        a = phone.line(LISTENING, False)
        phone.ms += 15 * 60000
        phone.up += 15 * 60000
        phone.charge += 200_000
        b = phone.line(LISTENING, False)
        self.assertEqual(probe(['exclude\t%s|%s' % (a, b)]), ['charged between samples'])

    def test_listener_cost_is_screen_off_drain_minus_the_listener_off_baseline(self):
        r = Phone().stretch(LISTENING, False, 8, 40).stretch(OFF, False, 8, 15).report()
        self.assertAlmostEqual(r['capacity'], 3700, delta=40)
        self.assertAlmostEqual(r['cost_mah'], 25, delta=.5)
        self.assertAlmostEqual(r['cost'], 25 / 37, delta=.02)
        self.assertEqual(r['confidence'], 'Estimate')
        self.assertTrue(r['headline'].startswith('Listening costs about 0.7% per hour'), r['headline'])
        self.assertEqual(r['summary'], '0.7%/h')

    def test_without_a_charge_counter_whole_percent_levels_are_used(self):
        r = Phone(counter=False).stretch(LISTENING, False, 10, 74).stretch(OFF, False, 10, 37).report()
        self.assertTrue(r['capacity'] != r['capacity'])
        self.assertTrue(r['cost_mah'] != r['cost_mah'])
        self.assertAlmostEqual(r['cost'], 1.0, delta=.25)

    def test_no_number_until_each_state_has_two_hours(self):
        early = Phone().stretch(LISTENING, False, 1.5, 40).report()
        self.assertEqual((early['summary'], early['confidence']), ('Measuring', 'Measuring'))
        self.assertTrue(early['cost'] != early['cost'])
        listening_only = Phone().stretch(LISTENING, False, 3, 40).stretch(OFF, False, 1.5, 15).report()
        self.assertTrue(listening_only['cost'] != listening_only['cost'])
        self.assertTrue(listening_only['summary'].endswith('/h total'), listening_only['summary'])
        self.assertEqual(listening_only['confidence'], 'Early estimate')
        steady = Phone().stretch(LISTENING, False, 24, 40).stretch(OFF, False, 24, 15).report()
        self.assertEqual(steady['confidence'], 'Steady estimate')

    def test_tiny_differences_read_as_within_standby_noise(self):
        r = Phone().stretch(LISTENING, False, 4, 15).stretch(OFF, False, 4, 16).report()
        self.assertEqual(r['cost'], 0.0)
        self.assertEqual(r['summary'], 'Under 0.1%/h')

    def test_listener_off_intervals_that_kept_the_phone_awake_are_treated_as_use(self):
        r = Phone().stretch(OFF, False, 4, 120, awake=.8).report()
        self.assertEqual((r['baseline_ms'], r['skipped']), (0, 16))

    def test_voice_use_restarts_and_other_microphone_use_are_left_out(self):
        phone = Phone()
        a = phone.line(LISTENING, False)
        phone.ms += 900000
        phone.up += 900000
        phone.wakes += 1
        self.assertEqual(probe(['exclude\t%s|%s' % (a, phone.line(LISTENING, False))]), ['voice use'])
        phone.boot = phone.ms  # elapsed restarts from the base after a reboot
        b = phone.line(LISTENING, False)
        self.assertEqual(probe(['exclude\t%s|%s' % (a, b)]), ['restart or clock change'])
        self.assertEqual(Phone().stretch(OTHER, False, 3, 200).report()['idle_ms'], 0)

    def test_long_gaps_and_malformed_rows_do_not_count(self):
        phone = Phone().stretch(LISTENING, False, 26, 40, step=13 * 60)
        self.assertEqual(phone.report()['idle_ms'], 0)
        rows = Phone().stretch(LISTENING, False, 3, 40).rows
        r = probe(rows[:3] + ['garbage', '1\t2\t3', ''] + rows[3:] + ['end'])[0].split('\t')
        self.assertEqual((int(r[0]), int(r[1])), (len(rows), 3 * HOUR))


if __name__ == '__main__':
    unittest.main()
