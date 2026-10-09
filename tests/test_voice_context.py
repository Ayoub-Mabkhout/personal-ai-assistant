"""Conversation and retry regressions using isolated stores and no inference."""
import base64
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
from personal_assistant.groceries.mobile import Devices
from personal_assistant.groceries.store import Groceries
from personal_assistant.relay.store import Queue
from personal_assistant.relay.voice import Capture,VoiceService,Transcriber


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
