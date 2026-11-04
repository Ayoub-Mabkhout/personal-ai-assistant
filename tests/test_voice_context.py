"""Conversation and retry regressions using isolated stores and no inference."""
import base64
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave
from personal_assistant.groceries.mobile import Devices
from personal_assistant.groceries.store import Groceries
from personal_assistant.relay.store import Queue
from personal_assistant.relay.voice import Capture,Typed,VoiceService,Transcriber


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.text='Find my latest electricity invoice.'
        self.service=VoiceService(root/'voice.sqlite3',Devices(root/'phones.sqlite3'),Groceries(root/'groceries.sqlite3'),
            Queue(root/'agents.sqlite3'),Queue(root/'commands.sqlite3'),transcribe=lambda *_:self.text)
        data=io.BytesIO()
        with wave.open(data,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\1\0'*4000)
        self.audio=data.getvalue()
    def body(self,identifier):
        return Capture(id=identifier,created_at=datetime.now(timezone.utc).isoformat(),
            audio_base64=base64.b64encode(self.audio).decode(),session_id='conversation-1')

    def test_followup_retains_exact_request_and_bounded_parent_receipt(self):
        first=self.service.capture('phone-a',self.body('first-command'))
        self.text='And download its attachment.';second_body=self.body('second-command')
        second=self.service.capture('phone-a',second_body)
        job=self.service.agents.get(second['task_id'])
        self.assertEqual(job['payload']['command'],self.text)
        context=job['payload']['reply_context']['recent_turns']
        self.assertEqual(context[0]['request'],'Find my latest electricity invoice.')
        self.assertEqual(context[0]['task_id'],first['task_id'])
        with self.service.ledger.db() as db:db.execute('UPDATE voice_commands SET result=NULL WHERE id=?',(second['task_id'],))
        self.assertEqual(self.service.capture('phone-a',second_body),second)
        self.assertEqual(self.service.agents.status()['queued'],2)

    def test_typed_request_is_queued_like_speech_and_replays_safely(self):
        body=Typed(id='typed-lock-0001',created_at=datetime.now(timezone.utc).isoformat(),text='Book a dentist appointment next week')
        first=self.service.typed('phone-a',body)
        self.assertEqual(self.service.agents.get(first['task_id'])['payload']['command'],'Book a dentist appointment next week')
        self.assertEqual(self.service.typed('phone-a',body),first)
        self.assertEqual(self.service.agents.status()['queued'],1)
        with self.assertRaises(Exception):
            self.service.typed('phone-a',Typed(id='typed-lock-0001',created_at=body.created_at,text='Something else'))

    def test_slow_capture_does_not_block_a_different_typed_command(self):
        started,release,typed_done=threading.Event(),threading.Event(),threading.Event()
        failures=[]
        def transcribe(*_):
            started.set()
            if not release.wait(5): raise RuntimeError('Test transcription was not released')
            return 'Find the latest invoice'
        self.service.transcribe=transcribe
        def capture():
            try: self.service.capture('phone-a',self.body('slow-capture'))
            except Exception as error: failures.append(error)
        def typed():
            try:
                self.service.typed('phone-a',Typed(id='fast-typed-command',
                    created_at=datetime.now(timezone.utc).isoformat(),text='hi'))
            except Exception as error: failures.append(error)
            finally: typed_done.set()
        recording=threading.Thread(target=capture)
        request=threading.Thread(target=typed)
        recording.start()
        try:
            self.assertTrue(started.wait(2))
            request.start()
            self.assertTrue(typed_done.wait(2),'Typed submission waited for unrelated transcription')
        finally:
            release.set()
            recording.join(5)
            if request.ident is not None: request.join(5)
        self.assertEqual(failures,[])
        identifier=self.service.identifier('phone-a','fast-typed-command')
        with self.service.ledger.db() as db:
            saved=db.execute('SELECT request FROM voice_commands WHERE id=?',(identifier,)).fetchone()
        marks=json.loads(saved['request'])['ingress_timing']
        self.assertGreater(marks['service_received_at'],0)
        self.assertGreaterEqual(marks['lock_wait_seconds'],0)
        self.assertEqual(marks['transcription_seconds'],0)
        self.assertGreaterEqual(marks['service_seconds'],marks['dispatch_seconds'])

    def test_concurrent_retries_share_one_transcription(self):
        started,release=threading.Event(),threading.Event()
        calls=[];answers=[];failures=[]
        body=self.body('shared-capture')
        def transcribe(*_):
            calls.append(1);started.set()
            if not release.wait(5): raise RuntimeError('Test transcription was not released')
            return 'hi'
        self.service.transcribe=transcribe
        def capture():
            try: answers.append(self.service.capture('phone-a',body))
            except Exception as error: failures.append(error)
        first=threading.Thread(target=capture);second=threading.Thread(target=capture)
        first.start()
        try:
            self.assertTrue(started.wait(2))
            second.start()
        finally:
            release.set()
            first.join(5)
            if second.ident is not None: second.join(5)
        self.assertEqual(failures,[])
        self.assertEqual(len(answers),2)
        self.assertEqual(answers[0],answers[1])
        self.assertEqual(calls,[1])
        self.assertEqual(self.service.agents.status()['queued'],1)

    def test_wake_only_and_stop_do_not_enter_agent_queue(self):
        self.text='Hej Chat!';answer=self.service.capture('phone-a',self.body('wake-only-command'))
        self.assertEqual(answer['status'],'no_command')
        self.text='Hey Chat, stop conversation.';answer=self.service.capture('phone-a',self.body('stop-conversation'))
        self.assertEqual(answer['status'],'ended');self.assertEqual(self.service.agents.status()['queued'],0)

    def test_failed_paid_attempts_have_distinct_budget_reservations(self):
        key=Path(self.tmp.name)/'dummy-key';key.write_text('not-an-api-key')
        transcriber=Transcriber({'key_file':str(key)},self.service.ledger)
        with patch('urllib.request.urlopen',side_effect=OSError('isolated failure')):
            for _ in range(2):
                with self.assertRaises(OSError):transcriber(self.audio,.25,'same-command')
        with self.service.ledger.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM voice_spend').fetchone()[0],2)
