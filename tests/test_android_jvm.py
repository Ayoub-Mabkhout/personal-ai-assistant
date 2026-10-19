"""Companion classes that need no Android framework, compiled with javac and driven through tests/jvm/AndroidLogicProbe.java.

Covers the sunrise and sunset maths behind the Sunrise & sunset theme (synthetic coordinates only; deployments configure
the real place privately), the continuous Daylight palette (WCAG AA through the whole day, polarity flips, weather), quick-add splitting, the voice status wording shared by the Voice tab, the locked entry
and the assistant overlay, the features checklist rules (offline replay, ordering, folding, retry outcomes) and the task
voice rules (including Stop dictation), and runs tests/jvm/DaylightThemeHarness.java. Skipped where no JDK is installed."""
import json
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
HARNESS = ROOT / 'tests/jvm/DaylightThemeHarness.java'
SOURCES = [COMPANION / name for name in ('DaylightTheme.java', 'DaylightPalette.java', 'ItemSplitter.java', 'VoiceStatus.java', 'FeatureBoard.java', 'TaskTurns.java', 'CaptureTurnPolicy.java')] + [PROBE, HARNESS]
MAIN = 'com.personalassistant.companion.AndroidLogicProbe'
# Synthetic round values; none of them stands for a real person's location.
PLACES = ((0.0, 0.0), (35.0, 120.0), (-33.0, -75.0))
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


def noaa(day, latitude, longitude):
    """Sunrise and sunset in epoch milliseconds from the NOAA general solar position equations; independent of the app's formulas."""
    gamma = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    equation = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma) - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    declination = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
                   + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    phi = math.radians(latitude)
    angle = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(declination)) - math.tan(phi) * math.tan(declination)))
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return tuple(ms(midnight + timedelta(minutes=720 - 4 * (longitude + sign * angle) - equation)) for sign in (1, -1))


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class DaylightThemeTests(unittest.TestCase):
    def sun(self, instants, place):
        rows = ask(['sun\t%d\t%s\t%s' % (at, *place) for at in instants])
        self.assertEqual(len(rows), len(instants))
        result = []
        for row in rows:
            times, dark, change = row.split('\t')
            result.append((None if times == 'null' else tuple(int(x) for x in times.split(',')), dark == 'true', int(change)))
        return result

    def test_sunrise_and_sunset_agree_with_an_independent_solar_model(self):
        days = [datetime(2026, month, day).date() for month in range(1, 13) for day in (1, 15)]
        for place in PLACES:
            got = self.sun([ms(datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc)) for d in days], place)
            for day, (times, _, _) in zip(days, got):
                with self.subTest(place=place, day=str(day)):
                    self.assertLessEqual(max(abs(a - b) for a, b in zip(times, noaa(day, *place))), 4 * 60000)

    def test_theme_flips_exactly_at_the_next_change(self):
        start = ms(datetime(2026, 1, 1, tzinfo=timezone.utc))
        instants = [start + n * 37 * 60000 for n in range(14200)]
        for place in PLACES:
            first = self.sun(instants, place)
            changes = [change for _, _, change in first]
            before = self.sun([change - 1000 for change in changes], place)
            after = self.sun([change + 1000 for change in changes], place)
            for at, (_, dark, change), (_, dark_before, _), (_, dark_after, _) in zip(instants, first, before, after):
                if not change > at or change - at > 20 * 3600000 or dark_before != dark or dark_after == dark:
                    self.fail('theme does not flip at the next change for %s at %d: %s' % (place, at, (dark, change, dark_before, dark_after)))

    def test_mid_latitudes_always_have_a_sunrise_and_sunset(self):
        for place in PLACES:
            for day in (datetime(2026, 6, 21, 12, tzinfo=timezone.utc), datetime(2026, 12, 21, 12, tzinfo=timezone.utc)):
                self.assertIsNotNone(self.sun([ms(day)], place)[0][0])

    def test_polar_summer_and_winter_have_no_sun_times(self):
        instants = [ms(datetime(2026, 12, 21, 12, tzinfo=timezone.utc)), ms(datetime(2026, 6, 21, 12, tzinfo=timezone.utc))]
        self.assertEqual([times for times, _, _ in self.sun(instants, (80.0, 0.0))], [None, None])

    def test_the_harness_for_boundaries_poles_fallback_and_refresh_planning_passes(self):
        run = subprocess.run([JAVA, '-cp', BUILD.name, 'com.personalassistant.companion.DaylightThemeHarness'], capture_output=True, text=True, check=True)
        result = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertTrue(result['passed'])
        self.assertGreater(result['checks'], 20)


TOKENS = ('background surface surfaceAlt text muted accent onAccent accentSoft stroke strokeStrong success successSoft warning '
          'warningSoft danger dangerSoft info infoSoft glow aurora0 aurora1 aurora2').split()
# Text and accent pairs that carry words or icons; each must stay WCAG AA (4.5:1) through the whole cycle.
AA_PAIRS = [('text', 'background'), ('muted', 'background'), ('accent', 'background'), ('text', 'surface'), ('muted', 'surface'),
            ('accent', 'surface'), ('text', 'surfaceAlt'), ('muted', 'surfaceAlt'), ('onAccent', 'accent'), ('onAccent', 'aurora0'),
            ('onAccent', 'aurora1'), ('accent', 'accentSoft'), ('success', 'background'), ('warning', 'background'), ('danger', 'background'),
            ('info', 'background'), ('success', 'successSoft'), ('warning', 'warningSoft'), ('danger', 'dangerSoft'), ('info', 'infoSoft')]
# Neutral synthetic places, from the tropics to beyond the polar circle.
DAYLIGHT_PLACES = ((45.0, 10.0), (0.0, 0.0), (-33.0, -75.0), (35.0, 120.0), (66.0, 25.0), (78.0, 15.0))
DAYLIGHT_DAYS = (datetime(2026, 3, 20, tzinfo=timezone.utc), datetime(2026, 6, 21, tzinfo=timezone.utc),
                 datetime(2026, 9, 23, tzinfo=timezone.utc), datetime(2026, 12, 21, tzinfo=timezone.utc))


def channel(value):
    value /= 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def luminance(color):
    return 0.2126 * channel(color >> 16 & 255) + 0.7152 * channel(color >> 8 & 255) + 0.0722 * channel(color & 255)


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def oklab(color):
    r, g, b = (channel(color >> shift & 255) for shift in (16, 8, 0))
    l, m, s = (math.copysign(abs(v) ** (1 / 3), v) for v in (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
                                                            0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
                                                            0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s, 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def elevation(moment, latitude, longitude):
    """Solar elevation in degrees from the NOAA general solar position (fractional year) equations, independent of the app."""
    gamma = 2 * math.pi / 365 * (moment.timetuple().tm_yday - 1 + (moment.hour - 12) / 24)
    equation = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma) - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    declination = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
                   + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    solar = moment.hour * 60 + moment.minute + moment.second / 60 + equation + 4 * longitude
    hour = math.radians(solar / 4 - 180)
    phi = math.radians(latitude)
    return 90 - math.degrees(math.acos(math.sin(phi) * math.sin(declination) + math.cos(phi) * math.cos(declination) * math.cos(hour)))


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class DaylightPaletteTests(unittest.TestCase):
    def palettes(self, instants, place, weather=0.0):
        rows = ask(['palette\t%d\t%s\t%s\t%s' % (at, place[0], place[1], weather) for at in instants])
        self.assertEqual(len(rows), len(instants))
        result = []
        for row in rows:
            colors, dark, height, hour = row.split('\t')
            result.append(([int(c, 16) for c in colors.split(',')], dark == 'true', float(height), float(hour)))
        return result

    def day(self, start, step_minutes):
        return [ms(start) + n * step_minutes * 60000 for n in range(24 * 60 // step_minutes)]

    def test_every_moment_of_the_day_keeps_text_and_accent_contrast_wcag_aa(self):
        worst = {}
        for place in DAYLIGHT_PLACES:
            for start in DAYLIGHT_DAYS:
                for weather in (0.0, 0.5, 1.0):
                    for palette, _, height, _ in self.palettes(self.day(start, 6), place, weather):
                        values = dict(zip(TOKENS, palette))
                        for front, back in AA_PAIRS:
                            ratio = contrast(values[front], values[back])
                            if ratio < worst.get((front, back), (99,))[0]:
                                worst[(front, back)] = (ratio, place, str(start.date()), weather, round(height, 2))
        failing = {pair: value for pair, value in worst.items() if value[0] < 4.5}
        self.assertEqual(failing, {})
        self.assertEqual(set(worst), set(AA_PAIRS))

    def test_bar_icons_follow_background_luminance_and_text_polarity(self):
        for place in DAYLIGHT_PLACES[:3]:
            for palette, dark, _, _ in self.palettes(self.day(DAYLIGHT_DAYS[0], 4), place):
                background, text = palette[0], palette[3]
                self.assertEqual(dark, luminance(background) < 0.179)
                self.assertEqual(dark, luminance(text) > luminance(background))

    def test_surface_colours_remain_continuous_across_foreground_flips(self):
        for place in DAYLIGHT_PLACES[:4]:
            rows = self.palettes(self.day(DAYLIGHT_DAYS[0], 1), place)
            flips = [i for i in range(1, len(rows)) if rows[i][1] != rows[i-1][1]]
            self.assertEqual(len(flips), 2)
            for i in flips:
                for token in [0, 1, 2, 7]:
                    self.assertLess(math.dist(oklab(rows[i-1][0][token]), oklab(rows[i][0][token])), .025)

    def test_colours_move_smoothly_between_the_two_polarity_flips(self):
        for place in ((45.0, 10.0), (66.0, 25.0)):
            for start in DAYLIGHT_DAYS:
                rows = self.palettes(self.day(start, 1), place)
                for before, after in zip(rows, rows[1:]):
                    if before[1] != after[1]:
                        continue
                    step = max(math.dist(oklab(before[0][i]), oklab(after[0][i])) for i in [0, 1, 2, 7, 8, 11, 13, 15, 17, 18])
                    self.assertLess(step, 0.02, (place, str(start.date())))

    def test_day_and_night_plateaus_are_the_light_and_dark_palettes(self):
        keys = [[int(c, 16) for c in row.split(',')] for row in ask(['keys'])]
        light, night = keys[0], keys[3]
        self.assertEqual((light[0], light[3], light[5]), (0xFAF5EC, 0x231A2E, 0x5B35D5))
        self.assertEqual((night[0], night[3], night[5]), (0x130E1C, 0xF5F0FB, 0xB39CFF))
        noon, midnight = self.palettes([ms(datetime(2026, 6, 21, 11, tzinfo=timezone.utc)), ms(datetime(2026, 6, 21, 23, tzinfo=timezone.utc))], (45.0, 10.0))
        self.assertEqual(noon[0], light)
        self.assertEqual(midnight[0], night)
        self.assertTrue(all(len(row) == len(TOKENS) for row in keys))

    def test_solar_elevation_agrees_with_an_independent_solar_model(self):
        moments = [datetime(2026, month, 10, hour, 30, tzinfo=timezone.utc) for month in range(1, 13) for hour in range(0, 24, 3)]
        for place in DAYLIGHT_PLACES:
            for moment, (_, _, height, _) in zip(moments, self.palettes([ms(m) for m in moments], place)):
                self.assertLess(abs(height - elevation(moment, *place)), 0.6, (place, moment))

    def test_weather_only_mutes_and_dims_a_little(self):
        rows = [float(x) for x in ask(['weather\t0\t', 'weather\t1\t', 'weather\t3\t', 'weather\t45\t', 'weather\t63\t', 'weather\t73\t',
                                        'weather\t95\t', 'weather\t-1\t', 'weather\t0\t100', 'weather\t500\t'])]
        clear, mainly, overcast, fog, rain, snow, storm, unknown, cloudy, invalid = rows
        self.assertEqual((clear, unknown, invalid), (0, 0, 0))
        self.assertTrue(0 < mainly < overcast < rain <= storm == 1)
        self.assertTrue(fog > overcast and snow > overcast)
        self.assertAlmostEqual(cloudy, 0.6)
        afternoon = ms(datetime(2026, 3, 20, 14, tzinfo=timezone.utc))
        (sunny, _, _, _), = self.palettes([afternoon], (45.0, 10.0), 0)
        (grey, _, _, _), = self.palettes([afternoon], (45.0, 10.0), 1)
        chroma = lambda color: math.hypot(*oklab(color)[1:])
        self.assertLess(chroma(grey[5]), chroma(sunny[5]))
        self.assertLess(oklab(grey[0])[0], oklab(sunny[0])[0])
        self.assertLess(oklab(sunny[0])[0] - oklab(grey[0])[0], 0.05)

    @unittest.skipUnless(shutil.which('node'), 'Node runs the shared web palette')
    def test_web_dashboard_palette_matches_the_companion(self):
        instants = [ms(datetime(2026, 3, 20, tzinfo=timezone.utc)) + n * 7 * 60000 for n in range(210)]
        script = ("const d=require(%s);const at=%s;for(const w of [0,0.6])for(const p of [{latitude:45,longitude:10},{latitude:-33,longitude:-75}])"
                  "for(const t of at)console.log(d.palette(t,p,w).map(c=>c.slice(1)).join(','));") % (json.dumps(str(ROOT / 'apps/shared/daylight.js')), json.dumps(instants))
        web = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, check=True).stdout.split()
        android = []
        for weather in (0, 0.6):
            for place in ((45.0, 10.0), (-33.0, -75.0)):
                android += [','.join('%06X' % c for c in row[0]) for row in self.palettes(instants, place, weather)]
        self.assertEqual(len(web), len(android))
        for a, b in zip(web, android):
            for x, y in zip(a.split(','), b.split(',')):
                self.assertLessEqual(max(abs((int(x, 16) >> s & 255) - (int(y, 16) >> s & 255)) for s in (0, 8, 16)), 1)


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
    for name in ('VoiceService.java', 'VoiceOutbox.java', 'MainActivity.java', 'VoiceEntryActivity.java', 'AssistantVoiceSession.java', 'MicrophoneTile.java', 'TaskVoice.java'):
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

    def test_task_voice_work_reads_as_working_not_as_listening(self):
        transcribing, waiting = self.status([('Transcribing your words…', 1, 0, 0, 1, 0, 1), ('Sent to this task · waiting for the task\'s answer', 1, 1, 0, 1, 0, 1)])
        self.assertEqual((transcribing[0], transcribing[2]), ('Transcribing...', 'working'))
        self.assertEqual((waiting[0], waiting[2]), ('Waiting for the answer', 'working'))
        # A finished preview receipt is not work in progress.
        self.assertNotEqual(self.status([('Transcription only. No action taken.', 1, 0, 0, 0, 0, 1)])[0][0], 'Transcribing...')


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class TaskVoiceRuleTests(unittest.TestCase):
    PHRASES = ('That was all.', 'That’s all', "that's all!", 'Hey Chat, end the conversation.', 'Please stop listening', 'Goodbye',
               "I'm done", 'Stop', 'Start conversation mode.', "Let's talk", 'Enter a conversation', 'Email Sam that was all I needed.',
               'Stop the heater', 'Use the second invoice', '', 'hej chat, that was all', 'Finish conversation mode?')

    def test_whole_request_controls_match_the_relay(self):
        from personal_assistant.relay.voice import conversation_control
        got = ask(['control\t' + phrase for phrase in self.PHRASES])
        for phrase, control in zip(self.PHRASES, got):
            with self.subTest(phrase=phrase):
                expected = {'command': 'end', 'conversation': 'start', None: 'none'}[conversation_control(phrase)]
                self.assertEqual(control, expected)

    def test_turn_ids_match_the_relay_continuation_ledger(self):
        import hashlib
        ids = ['3f2c9a6e-1b7d-4c55-9e0f-2a8b6d4c1e00', 'followup-id-001', 'x' * 64]
        for identifier, turn in zip(ids, ask(['turn\t' + i for i in ids])):
            self.assertEqual(turn, 'continue-' + hashlib.sha256(identifier.encode()).hexdigest()[:48])

    def test_dictation_joins_the_draft_at_the_caret_without_touching_the_rest(self):
        cases = [
            ('', 0, 0, ' Check the totals. ', ('Check the totals.', 17)),
            ('Use the', 7, 7, 'second invoice', ('Use the second invoice', 22)),
            ('Use the ', 8, 8, 'second invoice', ('Use the second invoice', 22)),
            ('Keep paragraph', 5, 5, 'the final', ('Keep the final paragraph', 14)),
            ('Keep the old paragraph', 9, 12, 'final', ('Keep the final paragraph', 14)),
            ('Done.', 4, 4, 'quickly', ('Done quickly.', 12)),
            ('Shorter', 99, 99, 'please', ('Shorter please', 14)),
            ('Shorter', -3, -3, 'please', ('please Shorter', 6)),
            ('Unchanged', 3, 3, '   ', ('Unchanged', 3)),
        ]
        got = ask(['insert\t%s\t%d\t%d\t%s' % (draft, start, end, words) for draft, start, end, words, _ in cases])
        for (draft, start, end, words, (text, caret)), row in zip(cases, got):
            with self.subTest(draft=draft, words=words):
                result, at, lo, piece = row.split('\t')
                self.assertEqual((result, int(at)), (text, caret))
                # The screen applies only the piece at the selection, so the rest of the draft keeps its spans and IME state.
                self.assertTrue(result.startswith(draft[:int(lo)] + piece))

    def test_settled_turns_are_spoken_briefly_and_waiting_turns_are_not(self):
        rows = [r.split('\t') for r in ask(['settle\tqueued\t', 'settle\trunning\t', 'settle\tcompleted\tThe invoice is **paid**. See https://example.invalid/x',
                                             'settle\tneeds_input\tWhich month?', 'settle\tfailed\tNo access.', 'settle\tcancelled\tignored',
                                             'settle\tcompleted\t', 'settle\tcompleted\t# Totals\\n- one\\n```\\ncode\\n```\\n' + 'Long sentence here. ' * 80])]
        self.assertEqual([r[0] for r in rows], ['wait', 'wait', 'answer', 'input', 'failed', 'cancelled', 'answer', 'answer'])
        self.assertEqual(rows[2][1], 'The invoice is paid. See a link')
        self.assertEqual(rows[3][1], 'Which month?')
        self.assertEqual(rows[4][1], 'That follow-up failed. No access.')
        self.assertEqual(rows[5][1], 'That follow-up was cancelled.')
        self.assertEqual(rows[6][1], 'Done. There is no written answer.')
        long = rows[7][1]
        self.assertTrue(long.startswith('Totals one (code is in the task) Long sentence here.'))
        self.assertTrue(long.endswith('. The full answer is in the task.'))
        self.assertLessEqual(len(long), 600 + len(' The full answer is in the task.'))
        self.assertNotIn('```', long)

    def test_composer_line_says_nothing_is_sent_while_dictating(self):
        rows = ask(['note\tdictate\tListening to your command…', 'note\tdictate\tTranscribing your words…', 'note\ttalk\tSent to this task · waiting for the task\'s answer',
                    'note\ttalk\tConversation mode · listening', 'note\tdictate\tStarting microphone...', 'note\ttalk\tMicrophone permission needed. Allow it in app settings.'])
        self.assertIn('Nothing is sent until you tap Send', rows[0])
        self.assertIn('Nothing is sent until you tap Send', rows[1])
        self.assertEqual(rows[2], 'Sent as a follow-up · waiting for the answer')
        self.assertIn('That was all', rows[3])
        self.assertEqual(rows[4], 'Starting the microphone…')
        self.assertEqual(rows[5], 'Microphone permission needed. Allow it in app settings.')

    def test_stop_dictation_transcribes_what_was_said_instead_of_discarding_it(self):
        # stop, capture active, capture task, capture is a dictation, requested task, request is a dictation, fresh speech
        cases = [
            (('t1', 1, 't1', 1, '', 0, 6400), 'finish'),   # words already said are transcribed into the draft
            (('t1', 1, 't1', 1, '', 0, 2400), 'finish'),
            (('t1', 1, 't1', 1, '', 0, 2399), 'drop'),     # nothing heard yet: the draft stays unchanged
            (('t1', 0, 't1', 1, '', 0, 6400), 'none'),     # transcription in flight: it still reaches the draft
            (('t1', 0, '', 0, 't1', 1, 0), 'cancel'),      # requested but not begun: withdrawn
            (('t1', 1, '', 0, 't1', 1, 6400), 'cancel'),   # a command capture is running and the dictation still waits
            (('t1', 1, 't1', 0, 't1', 0, 6400), 'none'),   # a task conversation turn is not a dictation
            (('t1', 1, 't2', 1, '', 0, 6400), 'none'),     # another task's dictation
            (('t1', 1, '', 0, '', 0, 6400), 'none'),       # an ordinary command capture
            (('', 1, 't1', 1, '', 0, 6400), 'none'),
        ]
        got = ask(['stop\t%s\t%d\t%s\t%d\t%s\t%d\t%d' % row for row, _ in cases])
        self.assertEqual(got, [expected for _, expected in cases])

    def test_stop_dictation_uses_the_capture_policys_speech_minimum(self):
        for fresh, row in zip((0, 2399, 2400, 12800), ask(['heard\t%d' % fresh for fresh in (0, 2399, 2400, 12800)])):
            stop, finished = row.split('\t')
            with self.subTest(fresh=fresh):
                self.assertEqual(stop == 'finish', finished == 'true')


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class FeatureBoardTests(unittest.TestCase):
    # id,done,created,doneAt: two open, two finished (d most recently).
    ITEMS = 'a,0,1,0;b,0,2,0;c,1,0.5,5;d,1,0.7,9'

    def board(self, changes, items=ITEMS):
        order, open_count, pending = ask(['board\t%s\t%s' % (items, changes)])[0].split('\t')
        return order, int(open_count), pending

    def fold(self, queue, change, sending=''):
        folded, rows = ask(['fold\t%s\t%s\t%s' % (queue, change, sending)])[0].split('\t')
        return folded == 'true', rows

    def test_open_items_come_first_in_creation_order_then_most_recently_finished(self):
        self.assertEqual(self.board(''), ('a,b,d+,c+', 2, ''))

    def test_checking_moves_an_item_to_the_top_of_finished_until_the_server_confirms(self):
        self.assertEqual(self.board('u1,update,a,1,10,,-'), ('b,a+,d+,c+', 1, 'a'))

    def test_unchecking_moves_a_finished_item_back_to_open(self):
        self.assertEqual(self.board('u1,update,d,0,10,,-'), ('d,a,b,c+', 3, 'd'))

    def test_offline_adds_show_at_once_and_can_be_finished_before_they_sync(self):
        self.assertEqual(self.board('c1,create,n1,-,20,,New'), ('a,b,n1,d+,c+', 3, 'n1'))
        self.assertEqual(self.board('c1,create,n1,-,20,,New;u1,update,n1,1,21,,-'), ('a,b,n1+,d+,c+', 2, 'n1'))
        self.assertEqual(self.board('c1,create,n1,-,20,,New', items=''), ('n1', 1, 'n1'))

    def test_deletes_hide_the_item_and_rejected_or_unknown_changes_do_not_apply(self):
        self.assertEqual(self.board('x1,delete,b,-,10,,-'), ('a,d+,c+', 1, ''))
        self.assertEqual(self.board('u1,update,a,1,10,needs_review,-'), ('a,b,d+,c+', 2, ''))
        self.assertEqual(self.board('u1,update,zz,1,10,,-'), ('a,b,d+,c+', 2, ''))

    def test_a_second_tick_folds_into_the_waiting_update_but_never_into_one_being_sent(self):
        self.assertEqual(self.fold('u1,update,a,1,10,,-', 'u2,update,a,0,11,,-'), (True, 'u1,update,a,0,-'))
        self.assertEqual(self.fold('u1,update,a,1,10,,-', 'u2,update,a,0,11,,-', 'u1'), (False, 'u1,update,a,1,-;u2,update,a,0,-'))
        self.assertEqual(self.fold('u1,update,a,1,10,,-;u2,update,b,1,10,,-', 'u3,update,a,-,11,,Renamed'), (True, 'u1,update,a,1,Renamed;u2,update,b,1,-'))
        self.assertEqual(self.fold('c1,create,n,-,10,,New', 'u1,update,n,1,11,,-'), (False, 'c1,create,n,-,New;u1,update,n,1,-'))
        self.assertEqual(self.fold('u1,update,a,1,10,needs_review,-', 'u2,update,a,0,11,,-'), (False, 'u1,update,a,1,-;u2,update,a,0,-'))

    def test_a_delete_drops_waiting_updates_but_keeps_the_create_and_anything_in_flight(self):
        self.assertEqual(self.fold('c1,create,n,-,10,,New;u1,update,n,1,11,,-', 'd1,delete,n,-,12,,-'), (False, 'c1,create,n,-,New;d1,delete,n,-,-'))
        self.assertEqual(self.fold('u1,update,a,1,10,,-', 'd1,delete,a,-,12,,-', 'u1'), (False, 'u1,update,a,1,-;d1,delete,a,-,-'))

    def test_titles_are_trimmed_and_kept_within_the_server_limit(self):
        rows = ask(['title\t  Wake   word  ', 'title\t   ', 'title\t' + 'x' * 250])
        self.assertEqual(rows, ['9\tWake word', 'null', '200\t' + 'x' * 200])

    def test_only_permanent_rejections_leave_the_retry_queue(self):
        cases = [('update', 404, 'drop'), ('delete', 404, 'drop'), ('create', 404, 'retry'), ('create', 422, 'drop'), ('create', 409, 'drop'),
                 ('update', 422, 'drop'), ('update', 400, 'review'), ('update', 500, 'retry'), ('delete', 401, 'retry'), ('update', 405, 'retry')]
        got = ask(['outcome\t%s\t%d' % (op, status) for op, status, _ in cases])
        self.assertEqual(got, [expected for _, _, expected in cases])


if __name__ == '__main__':
    unittest.main()
