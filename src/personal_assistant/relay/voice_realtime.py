"""Turn-based conversational voice over the same paired-phone PCM protocol."""
import asyncio
import base64
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time
import uuid
from zoneinfo import ZoneInfo

from fastapi import WebSocketDisconnect

from .voice_live import live_action
from .voice import conversation_control


INSTRUCTIONS = '''You are a concise, practical personal voice assistant.
The user's wake phrase is Hey Chat. Listen to the entire request, including
several items or instructions. Reply in the language the user speaks.
For every requested action and every personal or factual question, call
dispatch_request with the complete request. The backend handles shopping lists,
calendar, emails, documents, phone actions and a persistent laptop agent queue.
Do not invent account or list information. A queued receipt is not completion.
Wait for the backend result before reporting success. Give one short sentence
after routine results. For queued tasks, read the backend's request acknowledgement
once; do not promise a spoken completion or repeat it in later turns.
Greetings can be answered directly. If an essential word
is unclear, ask a short clarification. Do not treat background conversation,
music or coughing as requests. The phrases "That was all", "That's all", and
"end conversation" finish this conversation. When asked to stop, call the backend.'''

TOOL = {'type': 'function', 'name': 'dispatch_request',
        'description': 'Send the complete user request to the assistant backend. Preserve all requested items and instructions.',
        'parameters': {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 4096}},
                       'required': ['text'], 'additionalProperties': False}}


class PcmRate:
    """Preserve resampler phase across packets; never resample each frame afresh."""
    def __init__(self, source, target):
        self.source, self.target, self.state = source, target, None

    def convert(self, pcm):
        import audioop
        output, self.state = audioop.ratecv(pcm, 2, 1, self.source, self.target, self.state)
        return output


def usage_cost(usage):
    """Conservative non-cached token rates for the configured Realtime model."""
    inp = usage.get('input_token_details') or {}
    out = usage.get('output_token_details') or {}
    return (inp.get('audio_tokens', 0)*32 + inp.get('text_tokens', 0)*4
            + out.get('audio_tokens', 0)*64 + out.get('text_tokens', 0)*24) / 1_000_000


async def realtime_session(ws, service, phone):
    await ws.accept()
    if not service.config.get('key_file'):
        await ws.send_json({'type': 'error', 'message': 'Conversational speech is not configured. Use command mode.'})
        await ws.close()
        return
    started = time.monotonic()
    max_seconds = min(600, max(15, int(service.config.get('max_realtime_seconds', 300))))
    spend_id = None
    tasks = []
    ended = asyncio.Event()
    send_lock = asyncio.Lock()
    input_rate, output_rate = PcmRate(16000, 24000), PcmRate(24000, 16000)
    received_bytes = 0
    used = 0.0
    seen, pending_results = set(), []
    user_message_id, reply_id = '', ''

    async def emit(event):
        async with send_lock:
            await ws.send_json(event)

    try:
        initial = await asyncio.wait_for(ws.receive_json(), 10)
        session_id = initial.get('id', '')
        if initial.get('type') != 'start' or initial.get('sample_rate', 16000) != 16000:
            raise ValueError('Start a 16 kHz PCM16 session first.')
        if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', session_id):
            raise ValueError('Invalid session ID.')
        tz = initial.get('timezone', 'Europe/Berlin')
        ZoneInfo(tz)
        buffered = initial.get('buffered_audio_seconds', 2)
        if isinstance(buffered, bool) or not isinstance(buffered, (int, float)) or not math.isfinite(buffered) or not 0 <= buffered <= 60:
            raise ValueError('Invalid buffered audio duration.')
        spend_id = service.identifier(phone, 'realtime-'+session_id+':'+uuid.uuid4().hex)
        # Reserve audio and bounded text costs; reconcile returned usage at close.
        service.ledger.reserve(spend_id, max_seconds/60*.30,
                               service.config.get('monthly_budget_usd', 8), 'realtime')
        from websockets.asyncio.client import connect
        key = Path(service.config['key_file']).read_text().strip()
        model = service.config.get('realtime_model', 'gpt-realtime-2.1')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', model):
            raise ValueError('Invalid conversation model.')
        async with connect('wss://api.openai.com/v1/realtime?model='+model,
                           additional_headers={'Authorization': 'Bearer '+key},
                           open_timeout=15, max_size=2*1024*1024) as provider:
            await provider.send(json.dumps({'type': 'session.update', 'session': {
                'type': 'realtime', 'model': model, 'output_modalities': ['audio'],
                'instructions': INSTRUCTIONS, 'max_output_tokens': 256,
                'audio': {'input': {'format': {'type': 'audio/pcm', 'rate': 24000},
                                    'transcription': {'model': 'gpt-4o-mini-transcribe',
                                        'prompt': service.config.get('vocabulary', 'Voice commands. Hey Chat. Shopping list. Calendar. REWE.')[:1000]},
                                    'turn_detection': {'type': 'server_vad', 'threshold': .5,
                                        'prefix_padding_ms': 300, 'silence_duration_ms': 600,
                                        'create_response': True, 'interrupt_response': True}},
                          'output': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'voice': 'marin'}},
                'tools': [TOOL], 'tool_choice': 'auto'}}))

            async def commands():
                nonlocal received_bytes
                while not ended.is_set():
                    event = await ws.receive_json()
                    if event.get('type') == 'stop':
                        ended.set()
                        return
                    audio = event.get('audio', '')
                    if event.get('type') != 'audio' or not isinstance(audio, str) or len(audio) > 44000:
                        raise ValueError('Invalid voice frame.')
                    raw = base64.b64decode(audio, validate=True)
                    if len(raw) % 2:
                        raise ValueError('Incomplete PCM16 sample.')
                    received_bytes += len(raw)
                    if received_bytes > 32000*(time.monotonic()-started+buffered+2):
                        raise ValueError('Audio exceeds realtime stream rate.')
                    converted = input_rate.convert(raw)
                    if converted:
                        await provider.send(json.dumps({'type': 'input_audio_buffer.append',
                            'audio': base64.b64encode(converted).decode()}))

            async def events():
                nonlocal used, output_rate, user_message_id, reply_id
                ready = False
                async for encoded in provider:
                    event = json.loads(encoded)
                    kind = event.get('type')
                    if kind == 'session.updated' and not ready:
                        ready = True
                        await emit({'type': 'ready', 'sample_rate': 16000, 'engine': 'realtime'})
                    elif kind == 'input_audio_buffer.speech_started':
                        output_rate = PcmRate(24000, 16000)
                        reply_id = ''
                        await emit({'type': 'playback_reset'})
                    elif kind == 'response.output_audio.delta':
                        raw = base64.b64decode(event['delta'], validate=True)
                        converted = output_rate.convert(raw)
                        if converted:
                            await emit({'type': 'audio', 'audio': base64.b64encode(converted).decode()})
                    elif kind == 'response.output_audio_transcript.delta':
                        await emit({'type': 'transcript', 'role': 'assistant', 'text': event.get('delta', ''),
                                    'id': reply_id or event.get('response_id', session_id+':assistant')})
                    elif kind == 'conversation.item.input_audio_transcription.completed':
                        text=event.get('transcript','')
                        user_message_id=event.get('item_id') or session_id+':input:'+str(time.monotonic_ns())
                        await emit({'type': 'transcript', 'role': 'user', 'text': text,'id': user_message_id,'final': True})
                        if conversation_control(text)=='command':
                            # End controls are handled from the actual transcript, even
                            # when a conversation model elects not to call its tool.
                            identifier=service.identifier(phone,session_id+':end:'+user_message_id)
                            result=await asyncio.to_thread(live_action,service,phone,identifier,text,
                                tz,datetime.now(timezone.utc).isoformat(),session_id)
                            await provider.send(json.dumps({'type':'response.cancel'}))
                            await emit({'type':'playback_reset'})
                            await emit({'type':'status',**result,'user_message_id':user_message_id,'acknowledged':True})
                            ended.set()
                            return
                    elif kind == 'response.function_call_arguments.done':
                        call_id = event.get('call_id', '')
                        if call_id in seen:
                            continue
                        seen.add(call_id)
                        if event.get('name') != 'dispatch_request':
                            raise ValueError('Unsupported voice tool.')
                        arguments = json.loads(event['arguments'])
                        text = arguments.get('text')
                        if set(arguments) != {'text'} or not isinstance(text, str) or not 1 <= len(text.strip()) <= 4096:
                            raise ValueError('Incomplete voice request.')
                        identifier = service.identifier(phone, session_id+':'+call_id)
                        result = await asyncio.to_thread(live_action, service, phone, identifier, text,
                            tz, datetime.now(timezone.utc).isoformat(), session_id)
                        reply_id=identifier
                        await emit({'type': 'status', **result, 'user_message_id':user_message_id,'acknowledged': True})
                        await provider.send(json.dumps({'type': 'conversation.item.create', 'item': {
                            'type': 'function_call_output', 'call_id': call_id, 'output': json.dumps(result)}}))
                        pending_results.append(result)
                    elif kind == 'response.done':
                        used += usage_cost(event.get('response', {}).get('usage', {}))
                        if pending_results:
                            finished = list(pending_results)
                            pending_results.clear()
                            if any(r.get('status') == 'ended' for r in finished):
                                ended.set()
                                return
                            await provider.send(json.dumps({'type': 'response.create'}))
                    elif kind == 'error':
                        await emit({'type': 'error', 'message': 'Conversational speech rejected an event. Use command mode if it persists.'})
                        ended.set()
                        return
            tasks = [asyncio.create_task(commands()), asyncio.create_task(events()), asyncio.create_task(ended.wait())]
            done, _ = await asyncio.wait(tasks, timeout=max_seconds, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception():
                    raise task.exception()
            ended.set()
            await emit({'type': 'closed', 'reason': 'ended' if done else 'session_time_limit'})
    except (WebSocketDisconnect, ConnectionError):
        pass
    except Exception as error:
        try:
            await emit({'type': 'error', 'message': str(error) if isinstance(error, ValueError)
                        else 'Conversational speech unavailable. Use command mode for a saved recording.'})
        except Exception:
            pass
    finally:
        ended.set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if spend_id:
            # Include separate input transcription; incomplete provider usage retains
            # a duration estimate rather than billing a failed/early session as free.
            seconds = min(max_seconds, time.monotonic()-started)
            service.ledger.settle(spend_id, max(used+received_bytes/32000/60*.01, seconds/60*.05))
        try:
            await ws.close()
        except Exception:
            pass
