"""Companion classes that need no Android framework, compiled with javac and driven through tests/jvm/AndroidLogicProbe.java.

Covers the sunrise and sunset maths behind the default theme, quick-add splitting and the voice status wording
shared by the Voice tab, the locked entry and the assistant overlay. Skipped where no JDK is installed."""
import math
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPANION = ROOT / 'apps/android/src/com/personalassistant/companion'
PROBE = ROOT / 'tests/jvm/AndroidLogicProbe.java'
SOURCES = [COMPANION / name for name in ('DaylightTheme.java', 'ItemSplitter.java', 'VoiceStatus.java')] + [PROBE]
MAIN = 'com.personalassistant.companion.AndroidLogicProbe'
LATITUDE, LONGITUDE = 48.137, 11.575
SEP = '\u001f'


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
    BUILD = tempfile.TemporaryDirectory(prefix='assistant-android-jvm-')
    for flags in (['--release', '8'], []):
        built = subprocess.run([JAVAC, '-encoding', 'UTF-8', *flags, '-d', BUILD.name, *map(str, SOURCES)], capture_output=True, text=True)
        if built.returncode == 0:
            return
    raise RuntimeError(built.stderr)


def tearDownModule():
    if BUILD:
        BUILD.cleanup()


def ask(lines):
    run = subprocess.run([JAVA, '-Dfile.encoding=UTF-8', '-cp', BUILD.name, MAIN], input='\n'.join(lines) + '\n', capture_output=True, text=True, encoding='utf-8', check=True)
    return run.stdout.splitlines()


def ms(moment):
    return int(moment.timestamp() * 1000)


def noaa(day):
    """Sunrise and sunset in epoch milliseconds from the NOAA general solar position equations; independent of the app's formulas."""
    gamma = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    equation = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma) - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    declination = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
                   + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    phi = math.radians(LATITUDE)
    angle = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(declination)) - math.tan(phi) * math.tan(declination)))
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return tuple(ms(midnight + timedelta(minutes=720 - 4 * (LONGITUDE + sign * angle) - equation)) for sign in (1, -1))


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class DaylightThemeTests(unittest.TestCase):
    def sun(self, instants, latitude=None):
        suffix = '' if latitude is None else '\t%s' % latitude
        rows = ask(['sun\t%d%s' % (at, suffix) for at in instants])
        self.assertEqual(len(rows), len(instants))
        result = []
        for row in rows:
            times, dark, change = row.split('\t')
            result.append((None if times == 'null' else tuple(int(x) for x in times.split(',')), dark == 'true', int(change)))
        return result

    def test_sunrise_and_sunset_match_published_values_for_the_default_place(self):
        golden = {
            (2026, 3, 20): (1773983916277, 1774027590658),
            (2026, 6, 21): (1782011680785, 1782069521942),
            (2026, 9, 23): (1790139750268, 1790183550705),
            (2026, 12, 21): (1797836549335, 1797866602565),
        }
        got = self.sun([ms(datetime(*day, 12, tzinfo=timezone.utc)) for day in golden])
        for (day, expected), (times, _, _) in zip(golden.items(), got):
            with self.subTest(day=day):
                self.assertLessEqual(max(abs(a - b) for a, b in zip(times, expected)), 1000)

    def test_sunrise_and_sunset_agree_with_an_independent_solar_model(self):
        days = [datetime(2026, month, day).date() for month in range(1, 13) for day in (1, 15)]
        got = self.sun([ms(datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc)) for d in days])
        for day, (times, _, _) in zip(days, got):
            with self.subTest(day=str(day)):
                self.assertLessEqual(max(abs(a - b) for a, b in zip(times, noaa(day))), 4 * 60000)

    def test_theme_flips_exactly_at_the_next_change(self):
        start = ms(datetime(2026, 1, 1, tzinfo=timezone.utc))
        instants = [start + n * 37 * 60000 for n in range(14200)]
        first = self.sun(instants)
        changes = [change for _, _, change in first]
        before = self.sun([change - 1000 for change in changes])
        after = self.sun([change + 1000 for change in changes])
        for at, (_, dark, change), (_, dark_before, _), (_, dark_after, _) in zip(instants, first, before, after):
            if not change > at or change - at > 20 * 3600000 or dark_before != dark or dark_after == dark:
                self.fail('theme does not flip at the next change for %d: %s' % (at, (dark, change, dark_before, dark_after)))

    def test_default_place_always_has_a_sunrise_and_sunset(self):
        for day in (datetime(2026, 6, 21, 12, tzinfo=timezone.utc), datetime(2026, 12, 21, 12, tzinfo=timezone.utc)):
            self.assertIsNotNone(self.sun([ms(day)])[0][0])

    def test_polar_summer_and_winter_have_no_sun_times(self):
        self.assertEqual([times for times, _, _ in self.sun([ms(datetime(2026, 12, 21, 12, tzinfo=timezone.utc)), ms(datetime(2026, 6, 21, 12, tzinfo=timezone.utc))], 80)], [None, None])


class ItemSplitterTests(unittest.TestCase):
    TABLE = [
        ('milk, eggs and bread', ['milk', 'eggs', 'bread']),
        ('Mac And Cheese, bananas', ['mac and cheese', 'bananas']),
        ('2 mac and cheese, milk', ['2 mac and cheese', 'milk']),
        ('organic mac and cheese', ['organic mac and cheese']),
        ('salt and pepper and bread', ['salt and pepper', 'bread']),
        ('oil and vinegar; basil', ['oil and vinegar', 'basil']),
        ('äpfel und birnen', ['äpfel', 'birnen']),
        ('milk, , eggs', ['milk', 'eggs']),
        (' milk ', ['milk']),
        ('', []),
    ]

    def split(self, texts):
        return [row.split(SEP) if row else [] for row in ask(['split\t' + text for text in texts])]

    @unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
    def test_quick_add_splits_into_items_and_keeps_common_pairs(self):
        got = self.split([text for text, _ in self.TABLE])
        for (text, expected), items in zip(self.TABLE, got):
            with self.subTest(text=text):
                self.assertEqual(items, expected)
                self.assertFalse(any('COMPOUND' in item for item in items))

    @unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
    def test_quick_add_respects_the_server_limits(self):
        many, long = self.split([', '.join('item%d' % n for n in range(120)), 'x' * 400])
        self.assertEqual((len(many), many[0], many[-1], len(long[0])), (100, 'item0', 'item99', 300))

    @unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
    def test_quick_add_agrees_with_the_server_splitter(self):
        from personal_assistant.groceries.store import split_items
        plain = [text for text, _ in self.TABLE if text not in ('2 mac and cheese, milk', 'organic mac and cheese')]
        for text, items in zip(plain, self.split(plain)):
            with self.subTest(text=text):
                self.assertEqual(items, split_items(text))


def status_strings():
    """Every status text the voice service, the Voice tab and the overlays write, as far as it is a plain literal."""
    found = set()
    for name in ('VoiceService.java', 'VoiceOutbox.java', 'MainActivity.java', 'VoiceEntryActivity.java', 'AssistantVoiceSession.java', 'MicrophoneTile.java'):
        text = (COMPANION / name).read_text(encoding='utf-8')
        for raw in re.findall(r'(?:\bstate\(|"voice_status",)"((?:[^"\\]|\\.)*)"', text):
            if raw:
                found.add(re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), raw))
    return sorted(found)


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class VoiceStatusTests(unittest.TestCase):
    def status(self, rows):
        lines = ['status\t%s\t%d\t%d\t%d\t%d\t%d\t%d' % row for row in rows]
        return [tuple(line.split('\t')) for line in ask(lines)]

    def test_the_voice_tab_and_the_locked_entry_say_the_same_thing(self):
        strings = status_strings()
        self.assertGreaterEqual(len(strings), 20)
        rows = []
        for raw in strings:
            for mic in (0, 1):
                for wake in (0, 1):
                    for test in (0, 1):
                        for conversation in (0, 1):
                            for pending in (0, 2):
                                rows.append((raw, mic, wake, test, conversation, pending))
        tab = self.status([row + (1,) for row in rows])
        locked = self.status([row + (0,) for row in rows])
        for row, inside, outside in zip(rows, tab, locked):
            raw, mic, wake, test = row[:4]
            low = raw.lower()
            loading = any(word in low for word in ('starting', 'preparing', 'loading'))
            if (wake and not mic and not loading) or (low.startswith('open ') and not test):
                continue
            with self.subTest(row=row):
                self.assertEqual((inside[0], inside[2], inside[3]), (outside[0], outside[2], outside[3]))
                if inside[0] not in ('Microphone off', 'Listening for Hey Chat'):
                    self.assertEqual(inside[1], outside[1])

    def test_command_capture_in_conversation_mode_reads_as_conversation_everywhere(self):
        raw = 'Listening to your command…'
        for row in self.status([(raw, 1, 1, 0, 1, 0, 1), (raw, 1, 1, 0, 1, 0, 0)]):
            self.assertEqual(row[:3], ('Conversation active', 'Speak naturally. Say That was all to end.', 'conversation'))

    def test_a_single_command_capture_reads_as_listening(self):
        raw = 'Listening to your command…'
        for inside in self.status([(raw, 1, 1, 0, 0, 0, 1), (raw, 1, 1, 0, 0, 0, 0)]):
            self.assertEqual((inside[0], inside[2]), ('Listening to you', 'listening'))

    def test_connecting_wins_over_conversation(self):
        for row in self.status([('Connecting conversation…', 1, 0, 0, 1, 0, 1), ('Connecting conversation…', 1, 0, 0, 1, 0, 0)]):
            self.assertEqual((row[0], row[2]), ('Connecting...', 'working'))

    def test_resume_wording_exists_only_where_there_is_a_resume_button(self):
        tab, locked = self.status([('Microphone off', 0, 1, 0, 0, 0, 1), ('Microphone off', 0, 1, 0, 0, 0, 0)])
        self.assertEqual(tab[0], 'Listening paused')
        self.assertEqual(locked[0], 'Microphone off')

    def test_offline_titles_follow_the_saved_commands(self):
        raw = 'No internet · voice command saved on this phone'
        saved, waiting, plain = self.status([(raw, 1, 1, 0, 0, 2, 1), (raw, 1, 1, 0, 0, 0, 1), (raw, 0, 0, 0, 0, 0, 1)])
        self.assertEqual((saved[0], waiting[0], plain[0]), ('Saved offline', 'Listening offline', 'Offline'))
        self.assertEqual({saved[2], waiting[2], plain[2]}, {'offline'})

    def test_open_the_app_is_only_said_outside_the_app(self):
        raw = 'Open voice controls to start microphone'
        inside, outside = self.status([(raw, 0, 0, 0, 0, 0, 1), (raw, 0, 0, 0, 0, 0, 0)])
        self.assertEqual((outside[0], outside[2]), ('Open the app to start', 'attention'))
        self.assertNotEqual(inside[0], outside[0])


if __name__ == '__main__':
    unittest.main()
