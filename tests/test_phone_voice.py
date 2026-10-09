"""Isolated phone voice contract tests; no live API, mailbox, list or task writes."""
import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from fastapi import FastAPI,HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from personal_assistant.groceries.mobile import Devices
from personal_assistant.groceries.store import Groceries
from personal_assistant.relay.api import BodyLimit
from personal_assistant.relay.store import Queue
from personal_assistant.relay.voice import Capture,VoiceService,VoiceLedger,Transcriber,decode_audio,voice_router,conversation_control
from personal_assistant.relay.voice_live import live_action
from personal_assistant.relay.voice_realtime import PcmRate,usage_cost
from starlette.websockets import WebSocketDisconnect


def recording(seconds=0.25,rate=16000,channels=1):
    data=io.BytesIO()
    with wave.open(data,'wb') as wav:
        wav.setnchannels(channels);wav.setsampwidth(2);wav.setframerate(rate)
        wav.writeframes(b'\x01\x00'*int(seconds*rate)*channels)
    return base64.b64encode(data.getvalue()).decode()


class PhoneVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.devices=Devices(self.root/'phones.sqlite3')
        pair=self.devices.exchange(self.devices.pairing()['code'],'Isolated test phone')
        self.phone=pair['id'];self.headers={'Authorization':'Bearer '+pair['token']}
        self.groceries=Groceries(self.root/'groceries.sqlite3')
        self.agents=Queue(self.root/'agents.sqlite3',serial=True)
        self.commands=Queue(self.root/'commands.sqlite3')
        self.calls=[];self.text='Hey Chat, add bananas and sparkling water to my shopping list.'
        def transcribe(audio,duration,identifier):
            self.calls.append(identifier);return self.text
        self.service=VoiceService(self.root/'voice.sqlite3',self.devices,self.groceries,self.agents,self.commands,transcribe=transcribe)
        self.app=FastAPI();self.app.add_middleware(BodyLimit);self.app.include_router(voice_router(self.service))
        @self.app.exception_handler(ValueError)
        async def invalid(request,error):return JSONResponse({'detail':str(error)},status_code=422)
        self.client=TestClient(self.app)

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def body(self,identifier='voice-test-0001',**changes):
        return {'id':identifier,'created_at':datetime.now(timezone.utc).isoformat(),
                'timezone':'Europe/Berlin','audio_base64':recording(),**changes}

    def post(self,body):return self.client.post('/groceries/v1/mobile/voice',json=body,headers=self.headers)

    def test_multi_item_command_durable_receipt_and_duplicate_upload(self):
        body=self.body();first=self.post(body);repeated=self.post(body)
        self.assertEqual(first.status_code,200);self.assertEqual(first.json(),repeated.json())
        self.assertEqual(first.json()['status'],'completed')
        self.assertEqual([r['name'] for r in self.groceries.snapshot()['items']],['bananas','sparkling water'])
        self.assertEqual(len(self.calls),1)
        restored=VoiceService(self.root/'voice.sqlite3',self.devices,self.groceries,self.agents,self.commands,
            transcribe=lambda *args:self.fail('Replay must not transcribe again.'))
        self.assertEqual(restored.capture(self.phone,Capture(**body)),first.json())

    def test_id_reuse_rejects_changed_audio_or_dry_run(self):
        body=self.body();self.assertEqual(self.post(body).status_code,200)
        for changed in ({'audio_base64':recording(0.5)},{'dry_run':True}):
            self.assertEqual(self.post({**body,**changed}).status_code,409)
        self.assertEqual(len(self.groceries.snapshot()['items']),2);self.assertEqual(len(self.calls),1)

    def test_crash_after_mutation_recovers_without_duplicating_items(self):
        body=Capture(**self.body());original=self.groceries.mutate
        def interrupted(mutation):original(mutation);raise OSError('simulated process boundary')
        with patch.object(self.groceries,'mutate',side_effect=interrupted):
            with self.assertRaises(OSError):self.service.capture(self.phone,body)
        recovered=self.service.capture(self.phone,body)
        self.assertEqual(recovered['status'],'completed')
        self.assertEqual(len(self.groceries.snapshot()['items']),2);self.assertEqual(len(self.calls),1)

    def test_dry_run_no_speech_and_stop_never_execute_actions(self):
        dry=self.post(self.body(dry_run=True)).json();self.assertEqual(dry['status'],'transcribed')
        self.text='';self.assertEqual(self.post(self.body('voice-empty-0001')).json()['status'],'no_speech')
        self.text='Hey Chat, stop listening.'
        self.assertEqual(self.post(self.body('voice-stop-0001')).json()['status'],'ended')
        self.assertEqual(self.groceries.snapshot()['items'],[])
        with self.agents.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

    def test_unknown_prompt_uses_agent_queue_once_and_acknowledges_offline(self):
        self.text='Hey Chat, find my latest electricity bill.';body=self.body()
        first=self.post(body).json();second=self.post(body).json()
        self.assertEqual(first,second);self.assertEqual(first['status'],'queued')
        self.assertIn('Waiting for the laptop',first['reply'])
        self.assertIn('Queued command to the laptop: find my latest electricity bill.',first['reply'])
        self.assertNotIn('task updates',first['reply'])
        job=self.agents.get(first['task_id'])
        self.assertEqual(job['payload']['command'],'find my latest electricity bill.')
        self.assertEqual(job['source'],'phone_voice')
        self.assertEqual([event['kind'] for event in self.agents.history(first['task_id'])],['submitted'])
        with self.commands.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

    def test_conversation_controls_are_direct_and_do_not_capture_substantive_requests(self):
        for n,phrase in enumerate(("Hey Chat, start conversation mode.","Let's talk!",'Enter a conversation mode.','That was all.','That’s all.','End the conversation.')):
            self.text=phrase;result=self.post(self.body('mode-control-'+str(n))).json()
            entering=n<3
            self.assertEqual(result['status'],'conversation_started' if entering else 'ended')
            self.assertEqual(result['mode'],'conversation' if entering else 'command')
        self.assertEqual(self.agents.status()['queued'],0)
        self.text='Email Sam that was all I needed.'
        queued=self.post(self.body('mode-substantive-request')).json()
        self.assertEqual(queued['status'],'queued')
        self.assertEqual(self.agents.get(queued['task_id'])['payload']['command'],self.text)

    def test_ready_queue_receipt_reads_request_once_without_completion_claim(self):
        self.agents.heartbeat('ready');self.text='Hey Chat, read my email daily.'
        result=self.post(self.body()).json()
        self.assertEqual(result['reply'],'Queued command to the laptop: read my email daily.')
        self.assertEqual(result['status'],'queued')
        self.assertEqual(self.agents.status()['queued'],1)

    def test_programmed_status_does_not_dispatch_and_reports_ready(self):
        self.agents.heartbeat('ready');self.text='Is my laptop connected?'
        result=self.post(self.body()).json()
        self.assertEqual(result['status'],'completed');self.assertEqual(result['connection']['laptop'],'ready')
        with self.agents.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

    def test_wake_phrase_without_command_does_not_create_unretryable_empty_job(self):
        self.text='Hey Chat.'
        response=self.post(self.body())
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'no_command')
        with self.agents.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

    def test_only_live_paired_device_token_can_submit(self):
        for headers in ({},{'Authorization':'Bearer owner'},{'Authorization':'Bearer pa_mobile_unknown'}):
            self.assertEqual(self.client.post('/groceries/v1/mobile/voice',json=self.body(),headers=headers).status_code,401)
        self.devices.revoke(self.phone);self.assertEqual(self.post(self.body()).status_code,401)
        self.assertEqual(self.calls,[])

    def test_malformed_and_incompatible_audio_rejected_before_asr(self):
        for changes in ({'audio_base64':'not base64!'}, {'audio_base64':base64.b64encode(b'not wav').decode()},
                        {'audio_base64':recording(rate=8000)}, {'audio_base64':recording(channels=2)},
                        {'audio_base64':recording(0.05)}, {'sample_rate':8000}, {'format':'mp3'},
                        {'created_at':'2026-10-07T12:00:00'}):
            with self.subTest(changes=changes):self.assertEqual(self.post(self.body(**changes)).status_code,422)
        self.assertEqual(self.calls,[])

    def test_voice_body_limit_allows_recordings_but_rejects_oversize(self):
        # Three-second WAV exceeds the generic 16 KiB relay limit.
        response=self.post(self.body(audio_base64=recording(3),dry_run=True))
        self.assertEqual(response.status_code,200)
        response=self.client.post('/groceries/v1/mobile/voice',content=b'x'*(5*1024*1024+1),headers=self.headers)
        self.assertEqual(response.status_code,413)

    def test_budget_reservations_are_transactional_and_unconfigured_provider_never_calls_api(self):
        ledger=VoiceLedger(self.root/'budget.sqlite3')
        def reserve(n):
            try:ledger.reserve('unique-'+str(n),0.2,1,'transcription');return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(10)))
        self.assertEqual(sum(results),5)
        transcriber=Transcriber({'provider':'local'},ledger)
        with patch('urllib.request.urlopen') as remote:
            audio,duration=decode_audio(Capture(**self.body()))
            with self.assertRaisesRegex(ValueError,'not configured'):transcriber(audio,duration,'local-001')
            remote.assert_not_called()

    def test_timer_recognition_returns_phone_action_without_laptop_dispatch(self):
        for index,text in enumerate(('Hey Chat set a timer for five minutes.', 'start a timer for one hour and thirty minutes', 'set a timer for nonsense')):
            self.text=text;body=self.body('native-timer-'+str(index),native_timers=True)
            first=self.post(body).json();self.assertEqual(first,self.post(body).json())
            self.assertEqual(first['status'],'local_command');self.assertEqual(first['local_command'],'timer')
            self.assertEqual(first['created_at'],body['created_at']);self.assertEqual(first['text'],text)
        with self.agents.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
        self.text='set a timer for five minutes';unsupported=self.post(self.body('old-timer-0001')).json()
        self.assertEqual(unsupported['status'],'timer_unsupported');self.assertIn('not started',unsupported['reply'])

    def test_live_timer_delegation_is_phone_owned_and_replay_is_stable(self):
        identifier=self.service.identifier(self.phone,'live-timer-0001');text='set a timer for two hours'
        created=datetime.now(timezone.utc).isoformat()
        result=live_action(self.service,self.phone,identifier,text,'Europe/Berlin',created,native_timers=True)
        self.assertEqual(result['status'],'local_command')
        self.assertEqual(live_action(self.service,self.phone,identifier,text,'Europe/Berlin',created,native_timers=True),result)
        with self.agents.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

    def test_both_live_engines_wait_for_authoritative_phone_timer_receipt(self):
        key=self.root/'mock-api-key';key.write_text('isolated-not-a-real-key')
        self.service.config.update(key_file=str(key),max_live_seconds=15,max_realtime_seconds=15)
        for engine in ('live','realtime'):
            sent=[];text='set a timer for five minutes';reply='Timer set for 5 minutes on this phone.'
            stream=({'type':'session.started'}, {'type':'session.input_transcript.delta','delta':text,'start_ms':0,'end_ms':500}, {'type':'session.delegation.created','delegation':{'id':'timer-call'},'offset_ms':500}, {'type':'session.closed'}) if engine=='live' else (
                {'type':'session.updated'}, {'type':'conversation.item.input_audio_transcription.completed','item_id':'timer-user','transcript':text}, {'type':'response.function_call_arguments.done','call_id':'timer-call','name':'dispatch_request','arguments':json.dumps({'text':text})}, {'type':'response.done','response':{'usage':{}}}, {'type':'error'})
            class Provider:
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                async def send(self,message):sent.append(json.loads(message))
                def __aiter__(self):
                    async def events():
                        for event in stream:
                            await asyncio.sleep(0);yield json.dumps(event)
                    return events()
            with self.subTest(engine=engine),patch('websockets.asyncio.client.connect',return_value=Provider()):
                with self.client.websocket_connect('/groceries/v1/mobile/voice/live?engine='+engine,headers=self.headers) as ws:
                    ws.send_json({'type':'start','id':'timer-'+engine+'-session','sample_rate':16000,'native_timers':True})
                    statuses=[]
                    while True:
                        event=ws.receive_json()
                        if event['type']=='status':
                            statuses.append(event);self.assertEqual(event['status'],'local_command');self.assertFalse(event['acknowledged'])
                            self.assertFalse(any(e['type'] in ('session.commentary.append','conversation.item.create') for e in sent))
                            ws.send_json({'type':'local_result','id':event['task_id'],'status':'timer_active','reply':reply})
                        if event['type']=='closed':break
                self.assertEqual(len(statuses),1)
                outputs=[e for e in sent if e['type']=='session.commentary.append'] if engine=='live' else [e for e in sent if e['type']=='conversation.item.create']
                self.assertEqual(len(outputs),1)
                self.assertEqual(outputs[0]['content'] if engine=='live' else json.loads(outputs[0]['item']['output'])['reply'],reply)
        self.assertEqual(self.agents.status()['queued'],0)

    def test_live_requires_paired_auth_and_explains_unconfigured_provider(self):
        with self.assertRaises(WebSocketDisconnect) as raised:
            with self.client.websocket_connect('/groceries/v1/mobile/voice/live'):pass
        self.assertEqual(raised.exception.code,4401)
        with self.client.websocket_connect('/groceries/v1/mobile/voice/live',headers=self.headers) as ws:
            message=ws.receive_json()
            self.assertEqual(message['type'],'error');self.assertIn('not configured',message['message'])

    def test_live_delegation_executes_once_and_conflicting_replay_fails(self):
        identifier=self.service.identifier(self.phone,'live-session:test-delegation')
        created=datetime.now(timezone.utc).isoformat()
        first=live_action(self.service,self.phone,identifier,self.text,'Europe/Berlin',created)
        second=live_action(self.service,self.phone,identifier,self.text,'Europe/Berlin',created)
        self.assertEqual(first,second);self.assertEqual(len(self.groceries.snapshot()['items']),2)
        with self.assertRaises(ValueError):live_action(self.service,self.phone,identifier,'Add milk to my shopping list.','Europe/Berlin',created)

    def test_mock_live_provider_backend_receipt_precedes_action_claim(self):
        key=self.root/'mock-api-key';key.write_text('isolated-not-a-real-key')
        self.service.config.update(key_file=str(key),max_live_seconds=15)
        sent=[]
        class Provider:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def send(self,message):sent.append(json.loads(message))
            def __aiter__(self):
                async def events():
                    for event in ({'type':'session.started'},
                                  {'type':'session.input_transcript.delta','delta':'Hey Chat, add milk to my shopping list.','start_ms':0,'end_ms':100},
                                  {'type':'session.delegation.created','delegation':{'id':'delegate-1'},'offset_ms':100},
                                  {'type':'session.closed'}):
                        await asyncio.sleep(0);yield json.dumps(event)
                return events()
        with patch('websockets.asyncio.client.connect',return_value=Provider()) as connection:
            with self.client.websocket_connect('/groceries/v1/mobile/voice/live',headers=self.headers) as ws:
                ws.send_json({'type':'start','id':'live-session-test','sample_rate':16000,'timezone':'Europe/Berlin'})
                events=[]
                while True:
                    event=ws.receive_json();events.append(event)
                    if event['type']=='closed':break
        statuses=[event for event in events if event['type']=='status']
        self.assertEqual(len(statuses),1);self.assertEqual(statuses[0]['status'],'completed')
        self.assertEqual([item['name'] for item in self.groceries.snapshot()['items']],['milk'])
        commentary=[event for event in sent if event['type']=='session.commentary.append']
        self.assertEqual(commentary[0]['content'],'Added milk.')
        connection.assert_called_once()

    def test_realtime_resampling_keeps_packet_phase_and_exact_order(self):
        from array import array
        original=array('h',[((i*997)%24000)-12000 for i in range(16000)]).tobytes()
        whole=PcmRate(16000,24000).convert(original)
        rate=PcmRate(16000,24000)
        fragmented=b''.join(rate.convert(original[i:i+640]) for i in range(0,len(original),640))
        self.assertEqual(fragmented,whole)
        self.assertAlmostEqual(len(whole)/2/24000,1,places=3)
        down=PcmRate(24000,16000)
        pieces=b''.join(down.convert(whole[i:i+958]) for i in range(0,len(whole),958))
        self.assertEqual(pieces,PcmRate(24000,16000).convert(whole))

    def test_realtime_tool_receipt_is_idempotent_and_response_waits_for_done(self):
        key=self.root/'mock-api-key';key.write_text('isolated-not-a-real-key')
        self.service.config.update(key_file=str(key),max_realtime_seconds=15,conversation_provider='realtime')
        sent=[]
        arguments=json.dumps({'text':'Hey Chat, add milk and eggs to my shopping list.'})
        class Provider:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def send(self,message):sent.append(json.loads(message))
            def __aiter__(self):
                async def events():
                    for event in ({'type':'session.updated'},
                        {'type':'input_audio_buffer.speech_started'},
                        {'type':'conversation.item.input_audio_transcription.completed','transcript':'Hey Chat, add milk and eggs to my shopping list.'},
                        {'type':'response.function_call_arguments.done','call_id':'call-one','name':'dispatch_request','arguments':arguments},
                        {'type':'response.function_call_arguments.done','call_id':'call-one','name':'dispatch_request','arguments':arguments},
                        {'type':'response.done','response':{'usage':{}}},
                        {'type':'response.output_audio.delta','delta':base64.b64encode(b'\x01\x00'*1200).decode()},
                        {'type':'error','error':{'code':'test-only-finished'}}):
                        await asyncio.sleep(0);yield json.dumps(event)
                return events()
        with patch('websockets.asyncio.client.connect',return_value=Provider()) as connection:
            with self.client.websocket_connect('/groceries/v1/mobile/voice/live',headers=self.headers) as ws:
                ws.send_json({'type':'start','id':'realtime-isolated-test','sample_rate':16000,'timezone':'Europe/Berlin','buffered_audio_seconds':10})
                events=[]
                while True:
                    event=ws.receive_json();events.append(event)
                    if event['type']=='closed':break
        self.assertEqual(events[0]['type'],'ready')
        self.assertIn('playback_reset',[event['type'] for event in events])
        self.assertEqual(len([event for event in events if event['type']=='status']),1)
        self.assertEqual([item['name'] for item in self.groceries.snapshot()['items']],['milk','eggs'])
        outputs=[event for event in sent if event['type']=='conversation.item.create']
        self.assertEqual(len(outputs),1)
        receipt=json.loads(outputs[0]['item']['output']);self.assertEqual(receipt['reply'],'Added milk, eggs.')
        self.assertEqual(len([event for event in sent if event['type']=='response.create']),1)
        self.assertGreater([e['type'] for e in sent].index('response.create'),[e['type'] for e in sent].index('conversation.item.create'))
        self.assertIn('gpt-realtime-2.1',connection.call_args.args[0])
        audio=[event for event in events if event['type']=='audio'][0]
        self.assertAlmostEqual(len(base64.b64decode(audio['audio']))/2/16000,.05,places=3)

    def test_invalid_buffer_credit_never_opens_paid_provider(self):
        key=self.root/'mock-api-key';key.write_text('isolated-not-a-real-key')
        self.service.config.update(key_file=str(key),max_realtime_seconds=15)
        for engine in ('live','realtime'):
            for credit in (-1,61,True,'60'):
                with self.subTest(engine=engine,credit=credit),patch('websockets.asyncio.client.connect') as connection:
                    with self.client.websocket_connect('/groceries/v1/mobile/voice/live?engine='+engine,headers=self.headers) as ws:
                        ws.send_json({'type':'start','id':'bad-credit-isolated','sample_rate':16000,'buffered_audio_seconds':credit})
                        event=ws.receive_json();self.assertEqual(event['type'],'error')
                        self.assertIn('buffered',event['message'])
                    connection.assert_not_called()

    def test_realtime_usage_prices_audio_and_text_separately(self):
        self.assertAlmostEqual(usage_cost({'input_token_details':{'audio_tokens':100,'text_tokens':50},
                                         'output_token_details':{'audio_tokens':40,'text_tokens':25}}),.00656)

    def test_end_phrase_closes_each_live_engine_without_model_delegation(self):
        key=self.root/'mock-api-key';key.write_text('isolated-not-a-real-key')
        self.service.config.update(key_file=str(key),max_realtime_seconds=15,max_live_seconds=15)
        for engine in ('realtime','live'):
            sent=[]
            stream=({'type':'session.updated'},{'type':'conversation.item.input_audio_transcription.completed','item_id':'end-user-item','transcript':'That was all.'}) if engine=='realtime' else (
                {'type':'session.started'},{'type':'session.input_transcript.delta','delta':'That was all.','start_ms':0,'end_ms':500})
            class Provider:
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                async def send(self,message):sent.append(json.loads(message))
                def __aiter__(self):
                    async def events():
                        for event in stream:
                            await asyncio.sleep(0);yield json.dumps(event)
                        await asyncio.sleep(1)
                    return events()
            with self.subTest(engine=engine),patch('websockets.asyncio.client.connect',return_value=Provider()):
                with self.client.websocket_connect('/groceries/v1/mobile/voice/live?engine='+engine,headers=self.headers) as ws:
                    ws.send_json({'type':'start','id':'stop-'+engine+'-isolated','sample_rate':16000})
                    events=[]
                    while True:
                        event=ws.receive_json();events.append(event)
                        if event['type']=='closed':break
                receipt=[e for e in events if e['type']=='status']
                self.assertEqual(len(receipt),1)
                self.assertEqual(receipt[0]['status'],'ended')
                self.assertEqual(receipt[0]['mode'],'command')
                self.assertTrue(receipt[0]['user_message_id'])
                self.assertFalse(any(e['type'] in ('response.create','session.commentary.append') for e in sent))
        self.assertEqual(self.agents.status()['queued'],0)
        self.assertEqual(self.groceries.snapshot()['items'],[])

    def test_legacy_live_queue_has_one_ack_and_does_not_poll_or_speak_completion(self):
        key=self.root/'mock-api-key';key.write_text('isolated-not-a-real-key')
        self.service.config.update(key_file=str(key),max_live_seconds=15)
        sent=[]
        class Provider:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def send(self,message):sent.append(json.loads(message))
            def __aiter__(self):
                async def events():
                    for event in ({'type':'session.started'},
                        {'type':'session.input_transcript.delta','delta':'Find my latest invoice.','start_ms':0,'end_ms':500},
                        {'type':'session.delegation.created','delegation':{'id':'queue-one'},'offset_ms':500}):
                        await asyncio.sleep(0);yield json.dumps(event)
                    # A former completion-polling task would run after two seconds.
                    await asyncio.sleep(2.1)
                    yield json.dumps({'type':'session.closed'})
                return events()
        with patch('websockets.asyncio.client.connect',return_value=Provider()),patch.object(self.agents,'get',side_effect=AssertionError('No default completion polling')) as get:
            with self.client.websocket_connect('/groceries/v1/mobile/voice/live',headers=self.headers) as ws:
                ws.send_json({'type':'start','id':'one-ack-isolated','sample_rate':16000})
                events=[]
                while True:
                    event=ws.receive_json();events.append(event)
                    if event['type']=='closed':break
            get.assert_not_called()
        receipts=[e for e in events if e['type']=='status']
        self.assertEqual(len(receipts),1);self.assertEqual(receipts[0]['status'],'queued')
        self.assertEqual(len([e for e in sent if e['type']=='session.commentary.append']),1)
