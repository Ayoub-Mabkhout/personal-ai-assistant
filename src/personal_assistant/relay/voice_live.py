"""Server-owned GPT-Live socket: paired phone PCM, private key, existing queues."""
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time
import uuid
from zoneinfo import ZoneInfo

from fastapi import WebSocketDisconnect
from .voice import conversation_control


INSTRUCTIONS = '''Speak concisely and plainly. You are the voice interface to a personal assistant.
Delegate every requested action and every factual question to the client backend.
The backend handles shopping, calendar, emails and other tasks, with a persistent
laptop agent queue. A queued receipt is not completion. Never announce an action
as completed without a backend result. Include separate requests in a discussion.
For greetings and casual discussion you can reply directly. If the user ends the
conversation with "That was all" or another end phrase, stop. Read the backend's
queued-request acknowledgement once; do not announce later task completions.
Do not invent account, calendar or shopping information.'''


def live_action(service,phone,identifier,text,tz,created,session_id=''):
    """Persist transcript and receipt; downstream IDs provide retry deduplication."""
    fingerprint=hashlib.sha256(text.encode()).hexdigest()
    with service.lock:
        with service.ledger.db() as db:
            old=db.execute('SELECT * FROM voice_commands WHERE id=?',(identifier,)).fetchone()
            if old and old['fingerprint']!=fingerprint:raise ValueError('Delegation ID changed content.')
            if old and old['result']:return json.loads(old['result'])
            if not old:db.execute('INSERT INTO voice_commands VALUES(?,?,?,?,?,NULL,?)',
                (identifier,phone,fingerprint,json.dumps({'timezone':tz,'created_at':created,'mode':'live','session_id':session_id}),text,time.time()))
        result=service.dispatch(phone,identifier,text,tz,created,session_id)
        with service.ledger.db() as db:db.execute('UPDATE voice_commands SET result=? WHERE id=?',(json.dumps(result),identifier))
        return result


async def live_session(ws,service,phone):
    await ws.accept()
    if not service.config.get('key_file'):
        await ws.send_json({'type':'error','message':'Live speech is not configured. Use command mode.'});await ws.close();return
    started=time.monotonic();spend_id=None;provider=None;tasks=[]
    max_seconds=min(600,max(15,int(service.config.get('max_live_seconds',600))))
    ended=asyncio.Event();send_lock=asyncio.Lock();user_segments=[];last_offset=-1;received_bytes=0;reply_id=''
    async def emit(event):
        async with send_lock:await ws.send_json(event)
    try:
        initial=await asyncio.wait_for(ws.receive_json(),10)
        if initial.get('type')!='start' or initial.get('sample_rate',16000)!=16000:
            raise ValueError('Start a 16 kHz PCM16 session first.')
        session_id=initial.get('id','')
        if not isinstance(session_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',session_id):raise ValueError('Invalid session ID.')
        tz=initial.get('timezone','Europe/Berlin');ZoneInfo(tz)
        buffered=initial.get('buffered_audio_seconds',2)
        if isinstance(buffered,bool) or not isinstance(buffered,(int,float)) or not math.isfinite(buffered) or not 0<=buffered<=60:
            raise ValueError('Invalid buffered audio duration.')
        # Reserve the maximum duration conservatively before establishing a paid socket.
        spend_id=service.identifier(phone,'live-'+session_id+':'+uuid.uuid4().hex)
        service.ledger.reserve(spend_id,max_seconds/60*0.05,service.config.get('monthly_budget_usd',8),'live')
        from websockets.asyncio.client import connect
        key=Path(service.config['key_file']).read_text().strip()
        async with connect('wss://api.openai.com/v1/live/sessions',additional_headers={'Authorization':'Bearer '+key},
                           open_timeout=15,max_size=2*1024*1024) as provider:
            await provider.send(json.dumps({'type':'session.start','session':{
                'model':service.config.get('live_model','gpt-live-1'),'instructions':INSTRUCTIONS,
                'audio':{'format':{'type':'audio/pcm','rate':16000},'output':{'voice':'marin'}},
                'delegation':{'type':'client'}}}))

            async def commands():
                nonlocal received_bytes
                while not ended.is_set():
                    event=await ws.receive_json();kind=event.get('type')
                    if kind=='stop':ended.set();return
                    if kind!='audio':raise ValueError('Unsupported voice event.')
                    audio=event.get('audio','')
                    if not isinstance(audio,str) or len(audio)>44000:raise ValueError('Voice frame too large.')
                    raw=base64.b64decode(audio,validate=True)
                    if len(raw)%2:raise ValueError('Incomplete PCM16 sample.')
                    received_bytes+=len(raw)
                    if received_bytes>32000*(time.monotonic()-started+buffered+2):raise ValueError('Audio exceeds realtime stream rate.')
                    await provider.send(json.dumps({'type':'session.input_audio.append','audio':audio}))

            async def events():
                nonlocal last_offset,reply_id
                seen=set()
                async for encoded in provider:
                    event=json.loads(encoded);kind=event.get('type')
                    if kind=='session.started':await emit({'type':'ready','sample_rate':16000})
                    elif kind=='session.output_audio.delta':await emit({'type':'audio','audio':event['delta']})
                    elif kind in ('session.input_transcript.delta','session.output_transcript.delta'):
                        role='user' if kind=='session.input_transcript.delta' else 'assistant'
                        delta=event.get('delta','');await emit({'type':'transcript','role':role,'text':delta,
                            'id':reply_id if role=='assistant' and reply_id else session_id+':'+role+':'+str(last_offset)})
                        if role=='user':
                            reply_id=''
                            user_segments.append((event.get('start_ms',0),event.get('end_ms',0),delta))
                            # Bound memory while preserving recent context and consumed position.
                            if len(user_segments)>400:user_segments[:100]=[]
                            pending=''.join(s[2] for s in user_segments if s[1]>last_offset).strip()
                            if conversation_control(pending)=='command':
                                identifier=service.identifier(phone,session_id+':end:'+str(last_offset))
                                result=await asyncio.to_thread(live_action,service,phone,identifier,pending,tz,
                                    datetime.now(timezone.utc).isoformat(),session_id)
                                await emit({'type':'playback_reset'})
                                await emit({'type':'status',**result,'user_message_id':session_id+':user:'+str(last_offset),'acknowledged':True})
                                ended.set();return
                    elif kind=='session.delegation.created':
                        delegation=event['delegation'];delegation_id=delegation['id']
                        if delegation_id in seen:continue
                        seen.add(delegation_id);offset=event.get('offset_ms',10**12)
                        relevant=[s for s in user_segments if s[1]>last_offset and s[0]<=offset]
                        text=''.join(s[2] for s in relevant).strip()
                        if not text:
                            await provider.send(json.dumps({'type':'session.commentary.append','delegation_id':delegation_id,
                                'content':'I did not receive a complete request. Please repeat it.'}));continue
                        identifier=service.identifier(phone,session_id+':'+delegation_id)
                        reply_id=identifier
                        created=datetime.now(timezone.utc).isoformat()
                        result=await asyncio.to_thread(live_action,service,phone,identifier,text,tz,created,session_id)
                        user_message_id=session_id+':user:'+str(last_offset)
                        last_offset=max((s[1] for s in relevant),default=last_offset)
                        await emit({'type':'status',**result,'user_message_id':user_message_id,'acknowledged':True})
                        await provider.send(json.dumps({'type':'session.commentary.append','delegation_id':delegation_id,'content':result['reply'][:1600]}))
                        if result['status']=='ended':ended.set();return
                    elif kind=='error':
                        await emit({'type':'error','message':'Live speech service rejected an event. Use command mode if it persists.'})
                        ended.set();return
                    elif kind=='session.closed':ended.set();return
            tasks.extend([asyncio.create_task(commands()),asyncio.create_task(events())])
            end_task=asyncio.create_task(ended.wait());tasks.append(end_task)
            done,_=await asyncio.wait(tasks,timeout=max_seconds,return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception():raise task.exception()
            ended.set()
            await provider.send(json.dumps({'type':'session.close'}))
            await emit({'type':'closed','reason':'ended' if done else 'session_time_limit'})
    except (WebSocketDisconnect,ConnectionError):pass
    except Exception as error:
        try:await emit({'type':'error','message':str(error) if isinstance(error,ValueError) else 'Live speech connection unavailable. Your saved command can use command mode.'})
        except Exception:pass
    finally:
        ended.set()
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        if spend_id:service.ledger.settle(spend_id,min(max_seconds,time.monotonic()-started)/60*0.05)
        try:await ws.close()
        except Exception:pass
