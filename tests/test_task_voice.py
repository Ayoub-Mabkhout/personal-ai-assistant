"""Voice on the native task details screen.

Source checks pin the Android wiring: dictation goes through the dry-run transcription path and the user's own Send,
a task conversation sends turns as follow-ups of the same task and never opens the live provider, and the microphone
permission is only requested by the app's existing flow. The real TaskVoice and TaskTurns also run on the JVM against
the in-memory shims below (tests/jvm/TaskVoiceHarness.java). Relay checks pin the server contract the phone relies on.
No phone, paid API or live server is used.
"""
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
from personal_assistant.groceries.mobile import Devices
from personal_assistant.groceries.store import Groceries
from personal_assistant.relay.mobile_tasks import mobile_task_router
from personal_assistant.relay.store import Queue
from personal_assistant.relay.voice import Capture, VoiceService, voice_router

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'apps/android/src/com/personalassistant/companion'


def source(name):
    return (APP / name).read_text(encoding='utf-8')


def between(text, start, end):
    """The source from the start marker up to the end marker that follows it."""
    first = text.index(start)
    return text[first:text.index(end, first)]


def recording(seconds=0.5):
    data = io.BytesIO()
    with wave.open(data, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b'\x01\x00' * int(seconds * 16000))
    return base64.b64encode(data.getvalue()).decode()


class TaskVoiceSourceTests(unittest.TestCase):
    def test_composer_keeps_its_tags_and_adds_labelled_48dp_voice_controls(self):
        screens = source('NativeTaskScreens.java')
        for tag in ('task_followup_input', 'task_followup_send', 'task_voice_dictate', 'task_voice_talk', 'task_voice_status'):
            self.assertIn('setTag("%s")' % tag, screens)
        self.assertIn('ui.iconButton("voice","Dictate an instruction",this::dictate)', screens)
        self.assertIn('ui.chip("Talk about this task","chat",this::talk)', screens)
        self.assertIn('new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48));mp.leftMargin', screens)
        self.assertIn('"Stop dictation"', screens)
        # Typed follow-ups still use the durable stable-ID outbox.
        self.assertIn('NativeTasks.enqueueFollowup(a,id,text)', screens)

    def test_microphone_permission_is_requested_only_by_the_existing_flow(self):
        requests = []
        for path in sorted(APP.glob('*.java')):
            text = path.read_text(encoding='utf-8')
            requests += [path.name for _ in re.finditer(r'requestPermissions\(new String\[\]\{"android\.permission\.RECORD_AUDIO"\}', text)]
            if path.name in ('NativeTaskScreens.java', 'TaskVoice.java', 'TaskTurns.java'):
                self.assertNotIn('requestPermissions', text, path.name)
                self.assertNotIn('SpeechRecognizer', text, path.name)
        self.assertEqual(requests, ['MainActivity.java'])
        main = source('MainActivity.java')
        self.assertIn('requestMic(true,target)', main)
        self.assertIn('else taskVoice(task);', main)

    def test_dictation_is_transcription_only_and_waits_for_send(self):
        voice = source('TaskVoice.java')
        self.assertIn('VoiceOutbox.upload(c,VoiceOutbox.envelope(id,pcm,"",true))', voice)
        self.assertIn('if(!"transcribed".equals(result.optString("status")))throw', voice)
        run = voice[voice.index('private static void run('):]
        draft = run.index('if(dictation||preview){')
        self.assertLess(draft, run.index('NativeTasks.enqueueFollowupWithId(c,task,text,id)'))
        block = run[draft:run.index('return;', draft)]
        self.assertIn('deliver(c,task,text)', block)
        self.assertNotIn('enqueue', block)

    def test_task_turns_never_open_the_live_provider_or_the_command_outbox(self):
        service = source('VoiceService.java')
        self.assertIn('if(conversationMode&&captureTask==null&&', service)
        submit = service[service.index('protected void submit('):]
        self.assertLess(submit.index('if(captureTask!=null){taskSubmit(pcm);return;}'), submit.index('VoiceOutbox.save('))
        # A dictation binds to exactly one capture; a later wake is an ordinary command again.
        self.assertIn('captureTask=taskTarget;captureDictation=taskDictation;if(taskDictation){taskTarget=null;taskDictation=false;}', service)
        # A task conversation is a conversation: it shares the conversation audio path and ends like one.
        start = service[service.index('private boolean taskStart('):]
        self.assertIn('if(!dictate){setConversation(true);', start[:start.index('private void taskSubmit(')])

    def test_phone_envelope_fields_are_accepted_by_the_relay(self):
        outbox = source('VoiceOutbox.java')
        line = next(l for l in outbox.splitlines() if 'static JSONObject envelope(' in l)
        keys = set(re.findall(r'\.put\("(\w+)"', line))
        self.assertIn('dry_run', keys)
        self.assertLessEqual(keys, set(Capture.model_fields))

    def test_a_silent_task_conversation_turn_ends_the_conversation_even_with_background_listening(self):
        service = source('VoiceService.java')
        # Every expired capture reports to the task path, whatever the wake setting; only then does the wake setting pick the status.
        self.assertIn('else if(CaptureTurnPolicy.expired(elapsed,voiced)||stopTask.equals("drop")){capture.cancel();taskDropped(stopTask.equals("drop"));'
                      'state(wake?"Listening locally for Hey Chat · experimental":"No speech heard");if(!wake){main.post(this::stopSelf);break;}}', service)
        dropped = between(service, 'private void taskDropped(', 'private void taskFinish(')
        self.assertNotIn('wake', dropped)
        # Ordinary command captures (no task) keep master's behaviour; a talk capture ends its conversation, so a later Hey Chat
        # is an ordinary command and the 30 s follow-up deadline is not needed to end it.
        self.assertIn('String task=captureTask;if(task==null)return;', dropped)
        self.assertIn('captureTask=null;captureDictation=false;', dropped)
        self.assertIn('else{followup=false;setConversation(false);', dropped)
        self.assertIn('"No speech heard · the conversation ended."', dropped)
        # Ending the conversation also forgets the requested task (setConversation clears taskTarget, the wait and task_voice).
        self.assertIn('if(!enabled){taskTarget=null;taskDictation=false;taskAwaiting=false;}', service)
        self.assertIn('if(!enabled)edit.remove("task_voice");', service)

    def test_the_microphone_is_free_while_a_task_answer_is_awaited(self):
        service, voice = source('VoiceService.java'), source('TaskVoice.java')
        host = between(service, 'private void taskSubmit(', 'private void taskDropped(')
        # Once the server holds the follow-up, the record loop stops discarding frames: Hey Chat, Talk and barge-in work again.
        # The wait is marked before the recorder is freed, so a capture that sees it free also sees the wait.
        self.assertIn('public void released(){main.post(()->{if(!current())return;taskAwaiting=true;followup=false;waiting=false;});}', host)
        # The answer is spoken only while no newer turn began and this task's conversation is still the active one.
        self.assertIn('public boolean talking(){return current()&&conversationMode&&task.equals(taskTarget);}', host)
        reply = next(line for line in host.splitlines() if 'public void reply(' in line)
        self.assertLess(reply.index('if(!talking())return;'), reply.index('speakReply(text)'))
        self.assertLess(reply.index('if(!talking())return;'), reply.index('endConversation(false)'))
        # The answer reopens the conversation's own turns under the lock taskYield holds, so a capture never races it.
        self.assertIn('synchronized(VoiceService.this){if(!current())return;', reply)
        self.assertLess(reply.index('taskAwaiting=false;'), reply.index('speakReply(text)'))
        run = between(voice, 'private static void run(', 'private static void await(')
        self.assertLess(run.index('String pending=pendingState(c,id);'), run.index('host.released();'))
        self.assertLess(run.index('host.released();'), run.index('await(c,task,TaskTurns.turnId(id),host);'))
        wait = between(voice, 'private static void await(', 'private static String pendingState(')
        self.assertNotIn('host.current()', wait)
        self.assertIn('while(host.talking()&&', wait)
        # A task conversation awaiting its answer still counts as a conversation for the app (background off, theme changes).
        main = source('MainActivity.java')
        self.assertIn('private boolean taskTalk(){return AppUi.micActive(this)&&Cloud.prefs(this).getString("task_voice","").startsWith("talk:");}', main)
        self.assertIn('!p.getBoolean("voice_conversation_active",false)&&!taskTalk()&&', main)
        self.assertIn('if(Cloud.prefs(this).getBoolean("voice_conversation_active",false)||taskTalk())return true;', main)

    def test_hey_chat_or_talk_while_a_task_answer_is_awaited_ends_the_task_conversation(self):
        service = source('VoiceService.java')
        # A capture that begins during the wait ends the task conversation before it binds a task, a session or the live path,
        # and keeps the recorder it began on until it ends.
        begin = service[service.index('if(trigger||detected){'):]
        self.assertTrue(begin.startswith('if(trigger||detected){long wakeClock=SystemClock.elapsedRealtimeNanos();wakeStream.pause();taskYield();if(keepNextInput){keepNextInput=false;keepInput=true;}capture.begin(detected||followup);turnGeneration++;if(!conversationMode)session='))
        self.assertLess(begin.index('taskYield();'), begin.index('captureTask=taskTarget;'))
        self.assertIn('if(keepInput&&!capture.active())keepInput=false;\n                if(communicationInput!=conversationMode&&!keepInput){', service)
        # Talk (notification, lock screen entry, overlay) ends it before master's Talk path picks the session and follow-up mode.
        start = between(service, 'private boolean taskStart(', 'private void taskSubmit(')
        self.assertIn('if(!dictate&&!TASK_TALK.equals(action)){if(TALK.equals(action))taskYield();', start)
        command = between(service, 'public int onStartCommand(', 'protected int readMicrophone(')
        self.assertLess(command.index('boolean task=taskStart(intent);'), command.index('followup=conversationMode;'))
        # A new task conversation or a general conversation is never mistaken for a wait.
        self.assertIn('if(general){taskTarget=null;taskDictation=false;taskAwaiting=false;}', start)
        self.assertIn('turnGeneration++;waiting=false;taskAwaiting=false;taskTarget=task;', start)
        # Ending it is setConversation(false): task and task_voice cleared, audio routing restored; the screen hears why.
        yielded = between(service, 'private boolean taskYield(', 'private void taskDropped(')
        # Whichever thread yields (Talk yields on the main thread while the recorder thread may already be past its
        # recorder check), the next capture keeps the recorder it starts on instead of rebuilding it mid-command.
        self.assertIn('synchronized(this){if(!taskAwaiting)return false;String task=taskTarget;keepNextInput=true;setConversation(false);', yielded)
        self.assertIn('"Conversation ended · the answer will appear in this task."', yielded)

    def test_stop_dictation_finishes_the_capture_instead_of_cancelling_it(self):
        screens, service = source('NativeTaskScreens.java'), source('VoiceService.java')
        dictate = next(line for line in screens.splitlines() if 'void dictate(){' in line)
        self.assertIn('if(mode.equals("dictate"))finishDictation();', dictate)
        finish = next(line for line in screens.splitlines() if 'void finishDictation(){' in line)
        self.assertIn('TaskVoice.finish(a,id)', finish)
        self.assertNotIn('END_CONVERSATION', dictate + finish)
        # The end of a talk conversation still uses END_CONVERSATION.
        self.assertIn('void talk(){String mode=voiceMode();if(mode.equals("talk"))stopVoice();', screens)
        self.assertIn('if(intent!=null&&TASK_FINISH.equals(intent.getAction())){taskFinish(intent.getStringExtra("task_id"));return START_NOT_STICKY;}', service)
        stop = between(service, 'private void taskFinish(', 'Notification notification(')
        # Neither the tap nor the recorder's handling of it cancels a capture or invalidates a transcription in flight.
        for word in ('turnGeneration', 'cancelCapture', 'capture.cancel', 'endConversation'):
            self.assertNotIn(word, stop)
        self.assertIn('if(CaptureTurnPolicy.finished(elapsed,voiced,quiet,wakeCapture)||stopTask.equals("finish")){short[] pcm=capture.finish();waiting=true;', service)

    def test_the_screens_dictation_reads_never_wait_for_a_disk_write(self):
        voice = source('TaskVoice.java')
        storage = between(voice, 'static synchronized void deliver(', '/** Dry-run upload')
        # Each read-and-write stays atomic under the class lock; apply() updates memory at once and writes to disk off the lock.
        for name in ('deliver', 'take', 'note', 'takeNote'):
            self.assertRegex(storage, r'static synchronized \w+ %s\(' % name)
        self.assertNotIn('.commit()', storage)
        self.assertEqual(storage.count('.apply()'), 4)


def tool(name):
    found = shutil.which(name)
    home = os.environ.get('JAVA_HOME')
    if not found and home:
        candidate = Path(home) / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
        found = str(candidate) if candidate.is_file() else None
    return found


JAVAC, JAVA = tool('javac'), tool('java')
HARNESS = ROOT / 'tests/jvm/TaskVoiceHarness.java'

# Only what TaskVoice and the harness touch. Both writes update memory at once, as on Android; commit() then waits commitDelay
# for its disk write on the caller's thread, while apply() writes in the background.
SHIMS = {
    'android/content/Context.java': 'package android.content;public class Context {public Context getApplicationContext(){return this;}}',
    'android/content/Intent.java': r'''package android.content;import java.util.*;
public class Intent {String action;final Map<String,String> extras=new HashMap<String,String>();public Intent(Context c,Class<?> component){}
public Intent setAction(String a){action=a;return this;}public Intent putExtra(String k,String v){extras.put(k,v);return this;}public String getAction(){return action;}public String getStringExtra(String k){return extras.get(k);}}''',
    'android/content/SharedPreferences.java': r'''package android.content;import java.util.*;
public class SharedPreferences {public static volatile long commitDelay;public static final List<String> commits=Collections.synchronizedList(new ArrayList<String>());final Map<String,Object> data=new HashMap<String,Object>();
public String getString(String k,String d){synchronized(data){Object v=data.get(k);return v==null?d:v.toString();}}public boolean getBoolean(String k,boolean d){synchronized(data){Object v=data.get(k);return v==null?d:(Boolean)v;}}
public Editor edit(){return new Editor();}
public class Editor {final Map<String,Object> pending=new LinkedHashMap<String,Object>();public Editor putString(String k,String v){pending.put(k,v);return this;}public Editor putBoolean(String k,boolean v){pending.put(k,v);return this;}public Editor remove(String k){pending.put(k,null);return this;}
void memory(){synchronized(data){for(Map.Entry<String,Object> e:pending.entrySet())if(e.getValue()==null)data.remove(e.getKey());else data.put(e.getKey(),e.getValue());}}
public void apply(){memory();}
public boolean commit(){memory();commits.addAll(pending.keySet());try{Thread.sleep(commitDelay);}catch(InterruptedException e){Thread.currentThread().interrupt();}return true;}}}''',
    'org/json/JSONException.java': 'package org.json;public class JSONException extends Exception {public JSONException(String message){super(message);}}',
    'org/json/JSONObject.java': r'''package org.json;import java.util.*;
public class JSONObject {final Map<String,Object> map=new LinkedHashMap<String,Object>();public JSONObject put(String k,Object v)throws JSONException{if(v==null)map.remove(k);else map.put(k,v);return this;}
public JSONObject put(String k,boolean v)throws JSONException{map.put(k,v);return this;}public String optString(String k){return optString(k,"");}public String optString(String k,String d){Object v=map.get(k);return v==null?d:v.toString();}
public JSONObject optJSONObject(String k){Object v=map.get(k);return v instanceof JSONObject?(JSONObject)v:null;}public JSONArray optJSONArray(String k){Object v=map.get(k);return v instanceof JSONArray?(JSONArray)v:null;}}''',
    'org/json/JSONArray.java': r'''package org.json;import java.util.*;
public class JSONArray {final List<Object> list=new ArrayList<Object>();public int length(){return list.size();}public JSONArray put(Object v){list.add(v);return this;}
public JSONObject optJSONObject(int i){Object v=i>=0&&i<list.size()?list.get(i):null;return v instanceof JSONObject?(JSONObject)v:null;}
public JSONObject getJSONObject(int i)throws JSONException{JSONObject v=optJSONObject(i);if(v==null)throw new JSONException("Not an object");return v;}}''',
    'com/personalassistant/companion/Cloud.java': r'''package com.personalassistant.companion;
final class Cloud {static final android.content.SharedPreferences store=new android.content.SharedPreferences();static android.content.SharedPreferences prefs(android.content.Context c){return store;}}''',
    'com/personalassistant/companion/AppUi.java': 'package com.personalassistant.companion;final class AppUi {static boolean micActive(android.content.Context c){return true;}}',
    # The dry-run endpoint transcribes every capture to the same words.
    'com/personalassistant/companion/VoiceOutbox.java': r'''package com.personalassistant.companion;import org.json.*;
final class VoiceOutbox {static JSONObject envelope(String id,short[] audio,String session,boolean dryRun)throws JSONException{return new JSONObject().put("id",id).put("dry_run",dryRun);}
static JSONObject upload(android.content.Context c,JSONObject body)throws JSONException{return new JSONObject().put("status","transcribed").put("text","Use the second invoice");}
static boolean networkReady(android.content.Context c){return true;}}''',
    # Follow-ups of tasks in offline stay on the phone; the others reach the relay, whose turns answer at once unless the task is
    # running. Detail polls are counted per task.
    'com/personalassistant/companion/NativeTasks.java': r'''package com.personalassistant.companion;import java.util.*;import org.json.*;
final class NativeTasks {static final Set<String> offline=Collections.synchronizedSet(new HashSet<String>()),running=Collections.synchronizedSet(new HashSet<String>());
static final Map<String,Integer> counts=new HashMap<String,Integer>();static final Map<String,String> followups=new LinkedHashMap<String,String>();static final List<String> outbox=new ArrayList<String>();
static synchronized int polls(String task){Integer n=counts.get(task);return n==null?0:n;}
static synchronized String enqueueFollowupWithId(android.content.Context c,String task,String text,String id){followups.put(id,task);outbox.add(id);return id;}
static synchronized void flush(android.content.Context c){for(Iterator<String> it=outbox.iterator();it.hasNext();)if(!offline.contains(followups.get(it.next())))it.remove();}
static synchronized JSONArray pending(android.content.Context c)throws JSONException{JSONArray rows=new JSONArray();for(String id:outbox)rows.put(new JSONObject().put("id",id).put("task_id",followups.get(id)).put("state","saved"));return rows;}
static synchronized JSONObject detail(android.content.Context c,String kind,String task)throws JSONException{counts.put(task,polls(task)+1);JSONArray turns=new JSONArray();
for(Map.Entry<String,String> e:followups.entrySet())if(e.getValue().equals(task)&&!outbox.contains(e.getKey()))turns.put(new JSONObject().put("id",TaskTurns.turnId(e.getKey())).put("state",running.contains(task)?"running":"completed").put("summary","The answer for "+task+"."));
return new JSONObject().put("turns",turns);}
static void changed(android.content.Context c){}}''',
}


def service_shim():
    """VoiceService's intent actions, copied from the real source so the harness checks the actions the service handles."""
    constants = re.findall(r'(TASK_\w+)="([^"]+)"', source('VoiceService.java'))
    return 'package com.personalassistant.companion;final class VoiceService {static final String %s;}' % ','.join('%s="%s"' % pair for pair in constants)


def run_harness(main, sources, shims):
    """Compiles the real sources, a harness and its shims with javac, runs the harness once and returns its JSON report."""
    with tempfile.TemporaryDirectory(prefix='assistant-task-voice-') as build:
        root = Path(build) / 'shims'
        for name, body in shims.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(body, encoding='utf-8')
        classes = Path(build) / 'classes'
        files = [*sources, *sorted(root.rglob('*.java'))]
        for flags in (['--release', '8'], []):
            built = subprocess.run([JAVAC, '-encoding', 'UTF-8', '-nowarn', *flags, '-d', str(classes), *map(str, files)], capture_output=True, text=True)
            if built.returncode == 0:
                break
        else:
            raise RuntimeError(built.stderr)
        run = subprocess.run([JAVA, '-cp', str(classes), 'com.personalassistant.companion.' + main], capture_output=True, text=True, timeout=120)
    if run.returncode:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout.splitlines()[-1])


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class TaskVoiceHarnessTests(unittest.TestCase):
    """The real TaskVoice and TaskTurns, compiled with javac against the shims above and run once by tests/jvm/TaskVoiceHarness.java."""

    @classmethod
    def setUpClass(cls):
        cls.report = run_harness('TaskVoiceHarness', [APP / 'TaskVoice.java', APP / 'TaskTurns.java', HARNESS],
                                 {**SHIMS, 'com/personalassistant/companion/VoiceService.java': service_shim()})
        cls.actions = dict(re.findall(r'(TASK_\w+|END_CONVERSATION)="([^"]+)"', source('VoiceService.java')))

    def test_the_microphone_is_released_once_the_server_holds_the_follow_up_and_before_any_wait(self):
        for task in ('answer', 'ended', 'newer', 'late'):
            row = self.report[task]
            with self.subTest(task=task):
                self.assertEqual(row['events'][:4], ['state:Transcribing your words…', "state:Sent to this task · waiting for the task's answer", 'sent', 'released'])
                self.assertEqual(row['polls_at_release'], 0)

    def test_the_answer_is_read_aloud_while_the_conversation_is_on_and_no_newer_turn_began(self):
        answer = self.report['answer']
        self.assertEqual(answer['events'][4:], ['reply:The answer for answer.'])
        self.assertEqual(answer['polls'], 1)

    def test_an_ended_conversation_or_a_newer_turn_is_never_answered_aloud_and_stops_the_wait(self):
        for task in ('ended', 'newer', 'late'):
            with self.subTest(task=task):
                self.assertEqual(self.report[task]['events'][4:], [])
        # Ended, or replaced by a newer turn, as the microphone was freed: no poll at all. Replaced while polling: no further poll.
        self.assertEqual((self.report['ended']['polls'], self.report['newer']['polls'], self.report['late']['polls']), (0, 0, 1))
        self.assertLess(self.report['late_stop_ms'], 2000)
        self.assertFalse(self.report['workers_alive'])
        self.assertLess(self.report['turns_ms'], 20000)

    def test_a_follow_up_kept_offline_ends_the_conversation_without_releasing_a_wait(self):
        events = self.report['offline']['events']
        self.assertNotIn('released', events)
        self.assertEqual(events[-1], 'end:Saved on this phone. It will be sent to the task when you are connected.')
        self.assertEqual(self.report['offline']['polls'], 0)

    def test_stop_dictation_has_its_own_action_and_never_ends_the_conversation(self):
        self.assertEqual(self.report['finish_action'], self.actions['TASK_FINISH'])
        self.assertNotEqual(self.report['finish_action'], self.actions['END_CONVERSATION'])
        self.assertEqual(self.report['finish_task'], 'task-1')
        self.assertTrue(self.report['finish_rejects_bad_ids'])

    def test_the_screens_take_does_not_wait_for_a_disk_write(self):
        locks = self.report['locks']
        self.assertEqual((locks['taken'], locks['again'], locks['note'], locks['note_again']), ('Check the totals', '', 'Added to your draft', ''))
        # Every simulated disk write takes 1.5 s on its caller's thread; the main-thread take and takeNote never wait for one.
        self.assertLess(locks['take_ms'], 700)
        self.assertLess(locks['note_ms'], 700)
        self.assertLess(locks['deliver_ms'], 1400)
        self.assertEqual([key for key in locks['commits'] if key.startswith(('task_dictation:', 'task_voice_note:'))], [])

    def test_concurrent_dictation_is_neither_lost_nor_repeated(self):
        locks = self.report['locks']
        self.assertEqual((locks['race_words'], locks['race_unique']), (400, 400))


SERVICE_HARNESS = ROOT / 'tests/jvm/TaskVoiceServiceHarness.java'
# Compiled for real: the record loop, endpointing, pre-roll, wake gating, the task voice rules and the battery state rule.
SERVICE_SOURCES = ('VoiceService.java', 'WakeDetector.java', 'WakeStreamGate.java', 'CaptureSpeechGate.java', 'BufferedCapture.java',
                   'PcmRingBuffer.java', 'CaptureTurnPolicy.java', 'TaskTurns.java', 'DisabledWakeDetector.java', 'BatteryUsage.java')
# Everything else VoiceService touches. Main-thread posts run in order on one "main" thread; text to speech finishes each utterance
# at once on its own thread; the audio routing, recorder inputs, spoken text, saved commands and task turns go to one timeline.
# The live provider, notifications, timers and wake models only compile.
SERVICE_SHIMS = {
    'android/util/Timeline.java': r'''package android.util;import java.util.*;
public final class Timeline {public static final List<String> events=Collections.synchronizedList(new ArrayList<String>());public static void add(String event){events.add(event);}
public static List<String> copy(){synchronized(events){return new ArrayList<String>(events);}}}''',
    'android/util/Base64.java': 'package android.util;public class Base64 {public static final int DEFAULT=0;public static byte[] decode(String s,int flags){return java.util.Base64.getDecoder().decode(s);}}',
    'android/os/IBinder.java': 'package android.os;public interface IBinder {}',
    'android/os/Bundle.java': 'package android.os;public final class Bundle {}',
    'android/os/Build.java': 'package android.os;public class Build {public static class VERSION {public static final int SDK_INT=26;}}',
    'android/os/SystemClock.java': 'package android.os;public final class SystemClock {public static long elapsedRealtime(){return System.nanoTime()/1000000L;}public static long elapsedRealtimeNanos(){return System.nanoTime();}public static long uptimeMillis(){return elapsedRealtime();}}',
    'android/os/Looper.java': r'''package android.os;import java.util.concurrent.*;
public final class Looper {static final Looper MAIN=new Looper();final ExecutorService thread=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"main");t.setDaemon(true);t.setUncaughtExceptionHandler((th,e)->{android.util.Timeline.add("error:"+e);e.printStackTrace();});return t;});
public static Looper getMainLooper(){return MAIN;}
/** Runs on the main thread after everything posted before it, and waits. */
public static void run(Runnable r)throws Exception{MAIN.thread.submit(r).get(20,TimeUnit.SECONDS);}public static void idle()throws Exception{run(()->{});}}''',
    'android/os/Handler.java': 'package android.os;public class Handler {final Looper looper;public Handler(Looper l){looper=l;}public final boolean post(Runnable r){looper.thread.execute(r);return true;}public final boolean postDelayed(Runnable r,long ms){return post(r);}public final void removeCallbacks(Runnable r){}}',
    'android/os/PowerManager.java': 'package android.os;public final class PowerManager {public static final int PARTIAL_WAKE_LOCK=1,SCREEN_BRIGHT_WAKE_LOCK=10,ACQUIRE_CAUSES_WAKEUP=0x10000000;public WakeLock newWakeLock(int flags,String tag){return new WakeLock();}public final class WakeLock {boolean held;public void acquire(){held=true;}public void acquire(long ms){held=true;}public boolean isHeld(){return held;}public void release(){held=false;}}}',
    'android/os/Vibrator.java': 'package android.os;public class Vibrator {public void vibrate(VibrationEffect effect){}}',
    'android/os/VibrationEffect.java': 'package android.os;public class VibrationEffect {public static final int DEFAULT_AMPLITUDE=-1;public static VibrationEffect createOneShot(long ms,int amplitude){return new VibrationEffect();}}',
    'android/net/Network.java': 'package android.net;public class Network {}',
    'android/net/ConnectivityManager.java': 'package android.net;public class ConnectivityManager {public static class NetworkCallback {public void onAvailable(Network n){}public void onLost(Network n){}}public void registerDefaultNetworkCallback(NetworkCallback c){}public void unregisterNetworkCallback(NetworkCallback c){}}',
    'android/content/Context.java': r'''package android.content;
public class Context {public static final String NOTIFICATION_SERVICE="notification",POWER_SERVICE="power",CONNECTIVITY_SERVICE="connectivity",VIBRATOR_SERVICE="vibrator";
public Object getSystemService(String name){if(name.equals(NOTIFICATION_SERVICE))return new android.app.NotificationManager();if(name.equals(POWER_SERVICE))return new android.os.PowerManager();if(name.equals(CONNECTIVITY_SERVICE))return new android.net.ConnectivityManager();if(name.equals(VIBRATOR_SERVICE))return new android.os.Vibrator();return null;}
public <T> T getSystemService(Class<T> type){if(type==android.media.AudioManager.class)return type.cast(android.media.AudioManager.INSTANCE);if(type==android.os.PowerManager.class)return type.cast(new android.os.PowerManager());return null;}
public int checkSelfPermission(String permission){return 0;}public void sendBroadcast(Intent intent){}public String getPackageName(){return "com.personalassistant.companion";}
public android.content.res.AssetManager getAssets(){return new android.content.res.AssetManager();}public java.util.concurrent.Executor getMainExecutor(){return Runnable::run;}public Context getApplicationContext(){return this;}}''',
    'android/content/Intent.java': r'''package android.content;import java.util.*;
public class Intent {String action;final Map<String,String> extras=new HashMap<String,String>();public Intent(String action){this.action=action;}public Intent(Context c,Class<?> component){}
public Intent setAction(String a){action=a;return this;}public String getAction(){return action;}public Intent putExtra(String k,String v){extras.put(k,v);return this;}public String getStringExtra(String k){return extras.get(k);}public Intent setPackage(String p){return this;}}''',
    'android/content/SharedPreferences.java': r'''package android.content;import java.util.*;
public class SharedPreferences {final Map<String,Object> data=new HashMap<String,Object>();public void clear(){synchronized(data){data.clear();}}Object value(String k){synchronized(data){return data.get(k);}}
public String getString(String k,String d){Object v=value(k);return v==null?d:(String)v;}public boolean getBoolean(String k,boolean d){Object v=value(k);return v==null?d:(Boolean)v;}public long getLong(String k,long d){Object v=value(k);return v==null?d:(Long)v;}public float getFloat(String k,float d){Object v=value(k);return v==null?d:(Float)v;}
public Editor edit(){return new Editor();}
public class Editor {final Map<String,Object> pending=new LinkedHashMap<String,Object>();public Editor putString(String k,String v){pending.put(k,v);return this;}public Editor putBoolean(String k,boolean v){pending.put(k,v);return this;}public Editor putLong(String k,long v){pending.put(k,v);return this;}public Editor putFloat(String k,float v){pending.put(k,v);return this;}public Editor remove(String k){pending.put(k,null);return this;}
public void apply(){synchronized(data){for(Map.Entry<String,Object> e:pending.entrySet())if(e.getValue()==null)data.remove(e.getKey());else data.put(e.getKey(),e.getValue());}}public boolean commit(){apply();return true;}}}''',
    'android/content/pm/PackageManager.java': 'package android.content.pm;public class PackageManager {public static final int PERMISSION_GRANTED=0;}',
    'android/content/pm/ServiceInfo.java': 'package android.content.pm;public class ServiceInfo {public static final int FOREGROUND_SERVICE_TYPE_MICROPHONE=128;}',
    'android/content/res/AssetManager.java': 'package android.content.res;public class AssetManager {public String[] list(String path)throws java.io.IOException{return new String[0];}public java.io.InputStream open(String path)throws java.io.IOException{throw new java.io.FileNotFoundException(path);}}',
    'android/app/Service.java': r'''package android.app;
public abstract class Service extends android.content.Context {public static final int START_NOT_STICKY=2;
public void onCreate(){}public int onStartCommand(android.content.Intent intent,int flags,int startId){return START_NOT_STICKY;}public void onDestroy(){}public abstract android.os.IBinder onBind(android.content.Intent intent);
public final void startForeground(int id,Notification n){}public final void startForeground(int id,Notification n,int type){}public final void stopSelf(){android.util.Timeline.add("stopSelf");}}''',
    'android/app/Notification.java': r'''package android.app;
public class Notification {public static final String CATEGORY_SERVICE="service";
public static class Builder {public Builder(android.content.Context c,String channel){}public Builder setSmallIcon(int icon){return this;}public Builder setColor(int color){return this;}public Builder setColorized(boolean on){return this;}public Builder setCategory(String category){return this;}public Builder setSubText(CharSequence text){return this;}public Builder setContentTitle(CharSequence text){return this;}public Builder setContentText(CharSequence text){return this;}public Builder setContentIntent(PendingIntent intent){return this;}public Builder setOngoing(boolean on){return this;}public Builder addAction(Action action){return this;}public Notification build(){return new Notification();}}
public static class Action {public static class Builder {public Builder(android.graphics.drawable.Icon icon,CharSequence title,PendingIntent intent){}public Action build(){return new Action();}}}}''',
    'android/graphics/drawable/Icon.java': 'package android.graphics.drawable;public final class Icon {}',
    'android/app/NotificationManager.java': 'package android.app;public class NotificationManager {public static final int IMPORTANCE_LOW=2;public void notify(int id,Notification notification){}}',
    'android/app/PendingIntent.java': 'package android.app;public final class PendingIntent {public static final int FLAG_UPDATE_CURRENT=134217728,FLAG_IMMUTABLE=67108864;public static PendingIntent getActivity(android.content.Context c,int code,android.content.Intent i,int flags){return new PendingIntent();}public static PendingIntent getService(android.content.Context c,int code,android.content.Intent i,int flags){return new PendingIntent();}}',
    'android/media/MediaRecorder.java': 'package android.media;public class MediaRecorder {public static final class AudioSource {public static final int VOICE_RECOGNITION=6,VOICE_COMMUNICATION=7;}}',
    'android/media/AudioFormat.java': 'package android.media;public class AudioFormat {public static final int CHANNEL_IN_MONO=16,CHANNEL_OUT_MONO=4,ENCODING_PCM_16BIT=2;public static class Builder {public Builder setSampleRate(int r){return this;}public Builder setChannelMask(int m){return this;}public Builder setEncoding(int e){return this;}public AudioFormat build(){return new AudioFormat();}}}',
    'android/media/AudioAttributes.java': 'package android.media;public class AudioAttributes {public static final int USAGE_VOICE_COMMUNICATION=2,CONTENT_TYPE_SPEECH=1;public static class Builder {public Builder setUsage(int u){return this;}public Builder setContentType(int t){return this;}public AudioAttributes build(){return new AudioAttributes();}}}',
    'android/media/AudioTrack.java': 'package android.media;public class AudioTrack {public static final int MODE_STREAM=1,WRITE_BLOCKING=0;public static int getMinBufferSize(int r,int c,int e){return 6400;}public void play(){}public void pause(){}public void flush(){}public void stop(){}public void release(){}public int write(byte[] data,int offset,int size,int mode){return size;}public static class Builder {public Builder setAudioAttributes(AudioAttributes a){return this;}public Builder setAudioFormat(AudioFormat f){return this;}public Builder setBufferSizeInBytes(int n){return this;}public Builder setTransferMode(int m){return this;}public AudioTrack build(){return new AudioTrack();}}}',
    'android/media/AudioDeviceInfo.java': 'package android.media;public class AudioDeviceInfo {public static final int TYPE_WIRED_HEADSET=3,TYPE_WIRED_HEADPHONES=4,TYPE_BLUETOOTH_SCO=7,TYPE_BLUETOOTH_A2DP=8,TYPE_USB_HEADSET=22,TYPE_BLE_HEADSET=26;public int getType(){return 2;}}',
    'android/media/AudioRecordingConfiguration.java': 'package android.media;public class AudioRecordingConfiguration {public int getClientAudioSessionId(){return 0;}public boolean isClientSilenced(){return false;}}',
    'android/media/AudioManager.java': r'''package android.media;import android.util.Timeline;
public class AudioManager {public static final int MODE_NORMAL=0,MODE_IN_COMMUNICATION=3,GET_DEVICES_OUTPUTS=2;public static final AudioManager INSTANCE=new AudioManager();volatile int mode=MODE_NORMAL;volatile boolean speaker;
public int getMode(){return mode;}public void setMode(int m){mode=m;Timeline.add(m==MODE_IN_COMMUNICATION?"route:communication":"route:normal");}public boolean isSpeakerphoneOn(){return speaker;}public void setSpeakerphoneOn(boolean on){speaker=on;}
public AudioDeviceInfo[] getDevices(int flags){return new AudioDeviceInfo[0];}public void reset(){mode=MODE_NORMAL;speaker=false;}
public abstract static class AudioRecordingCallback {public void onRecordingConfigChanged(java.util.List<AudioRecordingConfiguration> configs){}}}''',
    'android/media/AudioRecord.java': r'''package android.media;import android.util.Timeline;
public class AudioRecord {public static final int STATE_INITIALIZED=1,READ_BLOCKING=0;
public AudioRecord(int source,int rate,int channel,int encoding,int bytes){Timeline.add(source==MediaRecorder.AudioSource.VOICE_COMMUNICATION?"input:communication":"input:recognition");}
public static int getMinBufferSize(int rate,int channel,int encoding){return 1280;}public int getState(){return STATE_INITIALIZED;}public int getAudioSessionId(){return 1;}public void startRecording(){}public void stop(){}public void release(){}
public int read(short[] data,int offset,int size,int mode){return size;}public void registerAudioRecordingCallback(java.util.concurrent.Executor e,AudioManager.AudioRecordingCallback callback){}}''',
    'android/media/audiofx/NoiseSuppressor.java': 'package android.media.audiofx;public class NoiseSuppressor {public static boolean isAvailable(){return false;}public static NoiseSuppressor create(int session){return null;}public int setEnabled(boolean on){return 0;}public void release(){}}',
    'android/media/audiofx/AcousticEchoCanceler.java': 'package android.media.audiofx;public class AcousticEchoCanceler {public static boolean isAvailable(){return false;}public static AcousticEchoCanceler create(int session){return null;}public int setEnabled(boolean on){return 0;}public void release(){}}',
    'android/speech/tts/UtteranceProgressListener.java': 'package android.speech.tts;public abstract class UtteranceProgressListener {public abstract void onStart(String id);public abstract void onDone(String id);public abstract void onError(String id);}',
    'android/speech/tts/TextToSpeech.java': r'''package android.speech.tts;import android.util.Timeline;import java.util.concurrent.*;
public class TextToSpeech {public static final int SUCCESS=0,ERROR=-1,QUEUE_FLUSH=0;public interface OnInitListener {void onInit(int status);}
final ExecutorService engine=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"tts");t.setDaemon(true);return t;});volatile UtteranceProgressListener listener;volatile long generation;
public TextToSpeech(android.content.Context c,OnInitListener init){init.onInit(SUCCESS);}public int setOnUtteranceProgressListener(UtteranceProgressListener l){listener=l;return SUCCESS;}
public int speak(CharSequence text,int queueMode,android.os.Bundle params,String id){final long g=++generation;Timeline.add("speak:"+text);engine.execute(()->{if(g!=generation)return;listener.onStart(id);try{Thread.sleep(30);}catch(InterruptedException e){return;}if(g==generation)listener.onDone(id);});return SUCCESS;}
public int stop(){generation++;return SUCCESS;}public void shutdown(){engine.shutdownNow();}}''',
    'org/json/JSONException.java': 'package org.json;public class JSONException extends Exception {public JSONException(String message){super(message);}}',
    'org/json/JSONObject.java': r'''package org.json;import java.util.*;
public class JSONObject {final Map<String,Object> map=new LinkedHashMap<String,Object>();public JSONObject put(String k,Object v)throws JSONException{if(v==null)map.remove(k);else map.put(k,v);return this;}public JSONObject put(String k,boolean v)throws JSONException{map.put(k,v);return this;}
public String optString(String k){return optString(k,"");}public String optString(String k,String d){Object v=map.get(k);return v==null?d:v.toString();}public boolean optBoolean(String k,boolean d){Object v=map.get(k);return v instanceof Boolean?(Boolean)v:d;}
public String getString(String k)throws JSONException{Object v=map.get(k);if(v==null)throw new JSONException("No value for "+k);return v.toString();}}''',
    'com/personalassistant/companion/Cloud.java': 'package com.personalassistant.companion;final class Cloud {static final android.content.SharedPreferences store=new android.content.SharedPreferences();static android.content.SharedPreferences prefs(android.content.Context c){return store;}}',
    'com/personalassistant/companion/R.java': 'package com.personalassistant.companion;final class R {static final class drawable {static final int ic_stat_assistant=1;}}',
    'com/personalassistant/companion/MainActivity.java': 'package com.personalassistant.companion;class MainActivity {}',
    'com/personalassistant/companion/NativeNotifications.java': 'package com.personalassistant.companion;final class NativeNotifications {static final int ACCENT=0;}',
    'com/personalassistant/companion/NotificationStyle.java': 'package com.personalassistant.companion;final class NotificationStyle {static void channel(android.app.NotificationManager m,String id,String name,int importance,String description){}}',
    'com/personalassistant/companion/BatterySampler.java': 'package com.personalassistant.companion;final class BatterySampler {static final class Watch {Watch(android.content.Context c){}void start(){}void stop(){}}}',
    'com/personalassistant/companion/TimerVoice.java': 'package com.personalassistant.companion;final class TimerVoice {static void recover(android.content.Context c){}static org.json.JSONObject apply(android.content.Context c,org.json.JSONObject event)throws Exception{throw new IllegalStateException("Timers are not part of this harness");}}',
    'com/personalassistant/companion/VoiceRetryJob.java': 'package com.personalassistant.companion;final class VoiceRetryJob {static void schedule(android.content.Context c){}}',
    'com/personalassistant/companion/VoiceChat.java': 'package com.personalassistant.companion;final class VoiceChat {static void user(android.content.Context c,String id,String text,long time){}static void assistant(android.content.Context c,String id,String text,long time){}static void assistant(android.content.Context c,String id,String text,long time,String kind,String taskId){}}',
    'com/personalassistant/companion/VoiceHistory.java': 'package com.personalassistant.companion;final class VoiceHistory {static boolean record(android.content.Context c,org.json.JSONObject event)throws Exception{return true;}}',
    'com/personalassistant/companion/VoiceSocket.java': r'''package com.personalassistant.companion;import org.json.JSONObject;
final class VoiceSocket {interface Listener {void event(JSONObject value);void closed(String message,boolean acknowledged);}
VoiceSocket(android.content.Context c,Listener l){android.util.Timeline.add("live");}void start(short[] preRoll){}boolean acknowledged(){return false;}boolean audio(short[] pcm,int n){return true;}void localResult(JSONObject receipt){}void disconnect(){}}''',
    'com/personalassistant/companion/VoskWakeDetector.java': 'package com.personalassistant.companion;final class VoskWakeDetector implements WakeDetector {public boolean accept(short[] f,int n){return false;}public boolean available(){return false;}public String name(){return "Vosk";}public void reset(){}void sensitivity(boolean sensitive){}String partial(){return "";}}',
    'com/personalassistant/companion/TemplateWakeDetector.java': 'package com.personalassistant.companion;final class TemplateWakeDetector implements WakeDetector {public boolean accept(short[] f,int n){return false;}public boolean available(){return false;}public String name(){return "Template";}public void reset(){}void add(short[] pcm){}void threshold(double value){}}',
    # The command outbox: each saved command is answered at once.
    'com/personalassistant/companion/VoiceOutbox.java': r'''package com.personalassistant.companion;import java.util.*;import org.json.*;
final class VoiceOutbox {interface Listener {void received(JSONObject result);void unavailable(String message);}static final List<short[]> saved=Collections.synchronizedList(new ArrayList<short[]>());
static String save(android.content.Context c,short[] audio,String session,boolean dryRun)throws Exception{android.util.Timeline.add("command");saved.add(audio);return "command-"+saved.size();}
static void retry(android.content.Context c,Listener listener){}static void retry(android.content.Context c,String id,Listener listener){try{listener.received(new JSONObject().put("status","completed").put("text","Add milk").put("reply","Added milk."));}catch(JSONException e){throw new IllegalStateException(e);}}
static boolean networkReady(android.content.Context c){return true;}static void refreshGroceries(android.content.Context c){}}''',
}


def service_shims():
    """SERVICE_SHIMS plus a TaskVoice that records each task turn and hands its host to the harness, which plays TaskVoice's part.
    The host interface is copied from the real TaskVoice, so VoiceService is compiled against the callbacks it really implements."""
    host = re.search(r'interface Host \{[^}]*\}', source('TaskVoice.java')).group(0)
    task_voice = ('package com.personalassistant.companion;import java.util.*;final class TaskVoice {%s\n'
                  'static final List<Host> hosts=Collections.synchronizedList(new ArrayList<Host>());static final List<String> notes=Collections.synchronizedList(new ArrayList<String>());\n'
                  'static void turn(android.content.Context c,short[] pcm,String task,boolean dictation,boolean preview,Host host){android.util.Timeline.add("task-turn:"+task);hosts.add(host);}\n'
                  'static void note(android.content.Context c,String task,String text){notes.add(task+": "+text);}}') % host
    return {**SERVICE_SHIMS, 'com/personalassistant/companion/TaskVoice.java': task_voice}


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class TaskVoiceServiceTests(unittest.TestCase):
    """The real VoiceService record loop with scripted microphone frames and Hey Chat model, run once by
    tests/jvm/TaskVoiceServiceHarness.java. A task conversation keeps its own turns; Hey Chat or Talk while it only awaits an
    answer ends it and runs as master's ordinary command."""

    @classmethod
    def setUpClass(cls):
        cls.report = run_harness('TaskVoiceServiceHarness', [*(APP / name for name in SERVICE_SOURCES), SERVICE_HARNESS], service_shims())

    def scenario(self, name):
        row = self.report[name]
        self.assertNotIn('failure', row)
        self.assertFalse([event for event in row['events'] if event.startswith('error:')])
        return row

    def test_hey_chat_while_a_task_answer_is_awaited_runs_as_an_ordinary_command(self):
        row = self.scenario('wake')
        events = row['events']
        # The task's own first turn, then Hey Chat: a wake capture (with master's pre-roll) saved as a command, not a follow-up.
        self.assertEqual([event for event in events if event.startswith('task-turn:')], ['task-turn:task-1'])
        self.assertEqual(row['commands'], ['wake command'])
        # The task conversation ends as the capture begins: audio routing restored and task voice cleared before the command.
        self.assertLess(events.index('wake'), events.index('route:normal'))
        self.assertLess(events.index('route:normal'), events.index('command'))
        self.assertEqual([event for event in events if event.startswith('route:')], ['route:communication', 'route:normal'])
        self.assertEqual((row['conversation_mode'], row['task_voice'], row['audio_mode'], row['speakerphone']), (False, '', 'normal', False))
        self.assertEqual(row['notes'], ['task-1: Conversation ended · the answer will appear in this task.'])
        # The command's reply is read aloud; the task's late answer is not (the task screen and its notification carry it).
        self.assertIn('speak:Added milk.', events)
        self.assertNotIn('speak:The answer for task-1.', events)
        self.assertEqual((row['first_turn_current'], row['first_turn_talking']), (False, False))
        self.assertEqual(row['voice_status'], 'Listening locally for Hey Chat')
        self.assertNotIn('live', events)

    def test_the_command_keeps_the_recorder_it_began_on(self):
        events = self.scenario('wake')['events']
        # No recorder swap between the wake and the saved command; the recognition input returns once the command ends.
        self.assertEqual([event for event in events if event.startswith('input:')], ['input:communication', 'input:recognition'])
        self.assertLess(events.index('command'), events.index('input:recognition'))

    def test_talk_while_a_task_answer_is_awaited_runs_as_an_ordinary_command(self):
        row = self.scenario('talk')
        events = row['events']
        self.assertEqual([event for event in events if event.startswith('task-turn:')], ['task-turn:task-1'])
        # As master's Talk outside a conversation: a fresh capture without the sound made before the tap.
        self.assertEqual(row['commands'], ['command'])
        self.assertLess(events.index('route:normal'), events.index('command'))
        # Like Hey Chat during the wait, the command keeps the recorder it began on; recognition input returns after it,
        # never by rebuilding the recorder in the middle of the command.
        self.assertEqual([event for event in events if event.startswith('input:')], ['input:communication', 'input:recognition'])
        self.assertLess(events.index('command'), events.index('input:recognition'))
        self.assertEqual((row['conversation_mode'], row['task_voice'], row['audio_mode']), (False, '', 'normal'))
        self.assertEqual(row['notes'], ['task-1: Conversation ended · the answer will appear in this task.'])
        self.assertIn('speak:Added milk.', events)
        self.assertNotIn('speak:The answer for task-1.', events)
        self.assertEqual((row['first_turn_current'], row['first_turn_talking']), (False, False))

    def test_the_follow_up_window_after_a_spoken_answer_still_belongs_to_the_task(self):
        row = self.scenario('window')
        events = row['events']
        # The answer is read aloud, and the next spoken turn in the follow-up window is the task's second turn, not a command.
        self.assertEqual(row['commands'], [])
        turns = [i for i, event in enumerate(events) if event == 'task-turn:task-1']
        self.assertEqual(len(turns), 2)
        self.assertLess(events.index('speak:The answer for task-1.'), turns[1])
        during = row['follow_up_turn']
        self.assertEqual((during['voice_conversation_mode'], during['task_voice'], during['audio_mode']), (True, 'talk:task-1', 'communication'))
        # That was all ends it as before: routing restored once, task voice cleared, nothing noted for the screen.
        self.assertIn('speak:Conversation ended.', events)
        self.assertEqual([event for event in events if event.startswith('route:')], ['route:communication', 'route:normal'])
        self.assertEqual((row['conversation_mode'], row['task_voice'], row['audio_mode'], row['notes']), (False, '', 'normal', []))

    def test_an_ordinary_hey_chat_command_is_unchanged(self):
        row = self.scenario('ordinary')
        self.assertEqual(row['events'], ['input:recognition', 'wake', 'command', 'speak:Added milk.'])
        self.assertEqual((row['commands'], row['task_turns'], row['conversation_mode'], row['audio_mode']), (['wake command'], 0, False, 'normal'))

    def test_a_task_answer_awaited_in_the_background_is_not_hey_chat_listening_for_battery(self):
        awaiting = self.scenario('wake')['awaiting']
        # Nothing is captured or spoken, so the loop reports no voice activity, yet the conversation's communication path is on.
        self.assertEqual((awaiting['voice_conversation_active'], awaiting['voice_conversation_mode'], awaiting['task_voice']), (False, True, 'talk:task-1'))
        self.assertEqual(awaiting['battery_mode'], 2)  # BatteryUsage.OTHER


class TaskVoiceRelayContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        self.devices = Devices(root / 'phones.sqlite3')
        phone = self.devices.exchange(self.devices.pairing()['code'], 'Isolated test phone')
        self.headers = {'Authorization': 'Bearer ' + phone['token']}
        self.agents = Queue(root / 'agents.sqlite3', serial=True); commands = Queue(root / 'commands.sqlite3')
        self.agents.submit({'id': 'original-task', 'command': 'Review the draft', 'timezone': 'Europe/Berlin'})
        self.spoken = 'Use the second invoice'
        service = VoiceService(root / 'voice.sqlite3', self.devices, Groceries(root / 'groceries.sqlite3'), self.agents, commands,
                               transcribe=lambda audio, duration, identifier: self.spoken)
        app = FastAPI(); app.include_router(voice_router(service)); app.include_router(mobile_task_router(self.devices, {'agent': self.agents, 'command': commands}))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close(); self.temp.cleanup()

    def jobs(self):
        with self.agents.connection() as db:
            return [row[0] for row in db.execute('SELECT id FROM jobs ORDER BY rowid')]

    def test_dry_run_transcribes_without_queueing_and_a_spoken_turn_continues_the_same_task(self):
        capture = '3f2c9a6e-1b7d-4c55-9e0f-2a8b6d4c1e00'
        body = {'id': capture, 'created_at': datetime.now(timezone.utc).isoformat(), 'timezone': 'Europe/Berlin', 'session_id': '',
                'sample_rate': 16000, 'format': 'wav', 'dry_run': True, 'audio_base64': recording()}
        transcribed = self.client.post('/groceries/v1/mobile/voice', json=body, headers=self.headers).json()
        self.assertEqual((transcribed['status'], transcribed['text']), ('transcribed', self.spoken))
        self.assertEqual(self.jobs(), ['original-task'])

        turn = {'id': capture, 'instruction': transcribed['text']}
        first = self.client.post('/groceries/v1/mobile/tasks/agent/original-task/followups', json=turn, headers=self.headers).json()
        again = self.client.post('/groceries/v1/mobile/tasks/agent/original-task/followups', json=turn, headers=self.headers).json()
        expected = 'continue-' + hashlib.sha256(capture.encode()).hexdigest()[:48]
        self.assertEqual((first['id'], first['root_id'], again['id'], again['created']), (expected, 'original-task', expected, False))
        detail = self.client.get('/groceries/v1/mobile/tasks/agent/original-task', headers=self.headers).json()
        self.assertEqual([(t['id'], t['instruction']) for t in detail['turns']], [(expected, self.spoken)])
        self.assertEqual(detail['original_request'], 'Review the draft')
        self.assertEqual(self.agents.get(expected)['payload']['resume_task'], {'root_id': 'original-task'})
        self.assertEqual(self.jobs(), ['original-task', expected])


if __name__ == '__main__':
    unittest.main()
