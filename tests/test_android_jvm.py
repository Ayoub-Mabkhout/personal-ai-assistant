"""Companion classes that need no Android framework, compiled with javac and driven through tests/jvm/AndroidLogicProbe.java.

Covers the sunrise and sunset maths behind the Sunrise & sunset theme (synthetic coordinates only; deployments configure
the real place privately), quick-add splitting, the voice status wording shared by the Voice tab, the locked entry
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
SOURCES = [COMPANION / name for name in ('DaylightTheme.java', 'ItemSplitter.java', 'VoiceStatus.java', 'FeatureBoard.java', 'TaskTurns.java', 'CaptureTurnPolicy.java')] + [PROBE, HARNESS]
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
