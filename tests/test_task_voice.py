"""Voice on the native task details screen.

Source checks pin the Android wiring: dictation goes through the dry-run transcription path and the user's own Send,
a task conversation sends turns as follow-ups of the same task and never opens the live provider, and the microphone
permission is only requested by the app's existing flow. Relay checks pin the server contract the phone relies on.
No phone, paid API or live server is used.
"""
import base64
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import re
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
