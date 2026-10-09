"""Paired-phone speech, durable receipts and native programmed/default-agent routing."""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.request
import uuid
import wave
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field


class Capture(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    created_at: str
    timezone: str = 'Europe/Berlin'
    audio_base64: str = Field(max_length=4_000_000)
    sample_rate: int = 16000
    format: str = 'wav'
    dry_run: bool = False
    native_timers: bool = False
    session_id: str = Field(default='', max_length=64)


def conversation_control(text):
    """Exact controls only: never discard a substantive request containing them."""
    cleaned=re.sub(r'^\s*(?:hey|hej|ej)[ ,]+chat[,.!? ]*','',text,flags=re.I).strip()
    cleaned=re.sub(r'^please\s+','',cleaned,flags=re.I)
    if re.fullmatch(r"(?:(?:start|enter|open) (?:a |the )?conversation(?: mode)?|conversation mode|let(?:['’]s| us) talk)[.!? ]*",cleaned,re.I):
        return 'conversation'
    if re.fullmatch(r"(?:stop|(?:end|finish|stop) (?:the )?conversation(?: mode)?|stop listening|goodbye|that was all|that['’]s all|I(?:['’]m| am) done)[.!? ]*",cleaned,re.I):
        return 'command'
    return None


def queued_reply(request,laptop):
    # The authoritative acknowledgement identifies the submitted instruction.
    # Keep speech bounded without rewriting its intent or changing queued content.
    spoken=re.sub(r'\s+',' ',request).strip().rstrip('.!? ')
    if len(spoken)>400:spoken=spoken[:397].rstrip()+'…'
    reply='Queued command to the laptop: '+spoken+'.'
    if laptop!='ready':reply+=' Waiting for the laptop.'
    return reply


def decode_audio(body):
    if body.format != 'wav' or body.sample_rate != 16000:
        raise ValueError('Use mono 16 kHz PCM16 WAV.')
    try:
        audio = base64.b64decode(body.audio_base64, validate=True)
        with wave.open(io.BytesIO(audio)) as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise ValueError('Use mono 16 kHz PCM16 WAV.')
            frames = wav.readframes(wav.getnframes())
            duration = len(frames) / 32000
            if not 0.15 <= duration <= 90 or len(frames) != wav.getnframes()*2:
                raise ValueError('Capture must contain 0.15–90 seconds of complete audio.')
    except (ValueError, wave.Error, EOFError) as error:
        raise ValueError('Invalid voice recording: '+str(error)) from None
    try:ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError,ValueError):raise ValueError('Unknown timezone.') from None
    created = datetime.fromisoformat(body.created_at)
    if created.tzinfo is None or created.timestamp() > time.time()+300:
        raise ValueError('Creation time needs an explicit UTC offset.')
    return audio, duration


class VoiceLedger:
    def __init__(self, path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS voice_commands (
                id TEXT PRIMARY KEY, phone TEXT NOT NULL, fingerprint TEXT NOT NULL,
                request TEXT NOT NULL, transcript TEXT, result TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS voice_spend (
                id TEXT PRIMARY KEY, month TEXT NOT NULL, dollars REAL NOT NULL, kind TEXT NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
        try:yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def reserve(self, identifier, amount, limit, kind):
        month=datetime.now(timezone.utc).strftime('%Y-%m')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT id FROM voice_spend WHERE id=?',(identifier,)).fetchone():return
            used=db.execute('SELECT COALESCE(SUM(dollars),0) FROM voice_spend WHERE month=?',(month,)).fetchone()[0]
            if used+amount>limit:raise ValueError('Configured API budget reached. No additional model call made.')
            db.execute('INSERT INTO voice_spend VALUES(?,?,?,?)',(identifier,month,amount,kind))

    def settle(self, identifier, amount):
        with self.db() as db:db.execute('UPDATE voice_spend SET dollars=? WHERE id=?',(amount,identifier))


class Transcriber:
    def __init__(self,config,ledger):self.config=config;self.ledger=ledger
    def __call__(self,audio,duration,identifier):
        if self.config.get('provider','openai')!='openai' or not self.config.get('key_file'):
            raise ValueError('Cloud speech transcription is not configured. Configure the OpenAI speech provider.')
        # Each network attempt reserves independently, including failures/retries.
        self.ledger.reserve(identifier+'-'+uuid.uuid4().hex,duration/60*0.01,self.config.get('monthly_budget_usd',8),'transcription')
        boundary='voice'+uuid.uuid4().hex
        parts=[]
        fields={'model':self.config.get('transcription_model','gpt-4o-mini-transcribe'),'response_format':'json',
                'prompt':self.config.get('vocabulary','Voice commands. Hey Chat. Shopping list. Calendar. REWE.')[:1000]}
        for name,value in fields.items():
            parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+name+'"\r\n\r\n'+value+'\r\n').encode())
        parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="capture.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()+audio+b'\r\n')
        data=b''.join(parts)+('--'+boundary+'--\r\n').encode()
        key=Path(self.config['key_file']).read_text().strip()
        request=urllib.request.Request('https://api.openai.com/v1/audio/transcriptions',data=data,
            headers={'Authorization':'Bearer '+key,'Content-Type':'multipart/form-data; boundary='+boundary})
        with urllib.request.urlopen(request,timeout=35) as response:return json.load(response)['text'].strip()


class VoiceService:
    def __init__(self,path,devices,groceries,agent_queue,command_queue,config=None,transcribe=None,shopping=None,interpret_groceries=None):
        self.ledger=VoiceLedger(path);self.devices=devices;self.groceries=groceries
        self.agents=agent_queue;self.commands=command_queue;self.config=config or {}
        self.transcribe=transcribe or Transcriber(self.config,self.ledger)
        from personal_assistant.groceries.intelligence import ShoppingIntelligence
        self.shopping=shopping or ShoppingIntelligence(groceries,self.config,self.ledger,interpret_groceries)
        self.lock=threading.Lock()

    @staticmethod
    def identifier(phone,identifier):return 'voice-'+hashlib.sha256((phone+':'+identifier).encode()).hexdigest()[:40]

    def capture(self,phone,body):
        audio,duration=decode_audio(body);identifier=self.identifier(phone,body.id)
        request=body.model_dump();request.pop('audio_base64');request['audio_sha256']=hashlib.sha256(audio).hexdigest()
        encoded=json.dumps(request,sort_keys=True);fingerprint=hashlib.sha256(encoded.encode()).hexdigest()
        # Serialize capture processing; downstream mutation/queue IDs survive crash/retry.
        with self.lock:
            with self.ledger.db() as db:
                old=db.execute('SELECT * FROM voice_commands WHERE id=?',(identifier,)).fetchone()
                if old and old['fingerprint']!=fingerprint:raise HTTPException(409,'Voice command ID already has different content.')
                if old and old['result']:return json.loads(old['result'])
                if not old:db.execute('INSERT INTO voice_commands VALUES(?,?,?,?,NULL,NULL,?)',(identifier,phone,fingerprint,encoded,time.time()))
            text=old['transcript'] if old and old['transcript'] is not None else self.transcribe(audio,duration,identifier)
            with self.ledger.db() as db:db.execute('UPDATE voice_commands SET transcript=? WHERE id=?',(text,identifier))
            if body.dry_run:result={'text':text,'reply':'Transcription only. No action taken.','status':'transcribed'}
            elif not text.strip():result={'text':'','reply':'I did not hear a command.','status':'no_speech'}
            else:result=self.dispatch(phone,identifier,text,body.timezone,body.created_at,body.session_id,body.native_timers)
            with self.ledger.db() as db:db.execute('UPDATE voice_commands SET result=? WHERE id=?',(json.dumps(result),identifier))
            return result

    def dispatch(self,phone,identifier,text,tz,created,session_id='',native_timers=False):
        from personal_assistant.groceries.intelligence import shopping_request
        cleaned=re.sub(r'^\s*(?:hey|hej|ej)[ ,]+chat[,.!? ]*','',text,flags=re.I).strip()
        base={'text':text,'task_id':identifier}
        if not cleaned:return {**base,'reply':'I’m listening.','status':'no_command'}
        # Only classify the request here; the paired phone owns parsing and execution.
        # Even malformed timer durations never escape into the laptop agent queue.
        if re.fullmatch(r'(?:please )?(?:can you |could you )?(?:set|start) (?:me )?(?:a |the )?timer(?:\s.*)?[.!? ]*',cleaned,re.I):
            if not native_timers:return {**base,'status':'timer_unsupported','reply':'Update Companion to use native timers. The timer has not started.'}
            return {**base,'status':'local_command','local_command':'timer','created_at':created,'reply':'Timer awaiting this phone.'}
        control=conversation_control(cleaned)
        if control=='conversation':
            return {**base,'reply':'Conversation mode on.','status':'conversation_started','mode':'conversation'}
        if control=='command':
            return {**base,'reply':'Conversation ended.','status':'ended','mode':'command'}
        if re.fullmatch(r'(?:is (?:my |the )?laptop (?:connected|online)|(?:check )?(?:laptop )?connection status)[?.! ]*',cleaned,re.I):
            status=self.agents.status();state=status['laptop']
            return {**base,'reply':'The laptop is ready.' if state=='ready' else 'The laptop is '+state+'. Commands are saved on the server.','status':'completed','connection':status}
        if re.fullmatch(r'(?:show|read|what(?: is|\'s)(?: on)?) (?:me )?(?:my |the )?shopping list[?.! ]*',cleaned,re.I):
            names=[r['name'] for r in self.groceries.snapshot()['items'] if not r['complete']]
            return {**base,'reply':', '.join(names) if names else 'Your shopping list is empty.','status':'completed'}
        if shopping_request(cleaned) and (self.config.get('key_file') or self.shopping.interpret):
            result=self.shopping.execute(identifier,cleaned)
            if result is not None:return {**base,**result}
        # Every other request enters the persistent Luna queue, without a prefix.
        payload={'id':identifier,'command':cleaned,'timezone':tz,'created_at':created}
        if session_id:
            # Freeze relevant history before queue submission so retries retain the
            # same envelope even if an earlier task completes in the meantime.
            with self.ledger.db() as db:
                row=db.execute('SELECT request FROM voice_commands WHERE id=?',(identifier,)).fetchone()
                request=json.loads(row['request']) if row else {}
                context=request.get('reply_context')
                if context is None:
                    recent=db.execute('SELECT id,request,transcript,result FROM voice_commands WHERE phone=? AND id!=? ORDER BY created DESC LIMIT 40',(phone,identifier)).fetchall()
                    relevant=[r for r in recent if json.loads(r['request']).get('session_id')==session_id and r['result']]
                    turns=[]
                    for previous in reversed(relevant[:6]):
                        receipt=json.loads(previous['result'])
                        if receipt.get('status') in ('queued','running'):
                            try:
                                current=self.agents.get(previous['id'])
                                receipt={**receipt,'status':current['state'],
                                    'task_result':{'summary':str((current.get('result') or {}).get('summary',''))[:3000]}}
                            except ValueError:pass
                        turns.append({'task_id':previous['id'],'request':previous['transcript'],'receipt':receipt})
                    context={'voice_session':session_id,'recent_turns':turns}
                    request['reply_context']=context
                    if row:db.execute('UPDATE voice_commands SET request=? WHERE id=?',(json.dumps(request),identifier))
                if context.get('recent_turns'):payload['reply_context']=context
        job,_=self.agents.submit(payload,source='phone_voice')
        status=self.agents.status()
        return {**base,'reply':queued_reply(cleaned,status['laptop']),'status':job['state'],'connection':status}


def voice_router(service):
    api=APIRouter(prefix='/groceries/v1/mobile/voice')
    def device(authorization:str|None=Header(default=None)):
        if not authorization or not authorization.startswith('Bearer pa_mobile_'):raise HTTPException(401,'Pair the companion first.')
        try:return service.devices.authenticate(authorization[7:])
        except ValueError:raise HTTPException(401,'Pair the companion again.') from None
    @api.post('')
    def capture(body:Capture,phone=Depends(device)):
        try:return service.capture(phone,body)
        except OSError:raise HTTPException(503,'Speech service unavailable. Recording remains queued on the phone.') from None
    @api.get('/status')
    def status(phone=Depends(device)):
        return {'connection':service.agents.status(),'live_available':bool(service.config.get('key_file')),
                'transcription_model':service.config.get('transcription_model','local')}
    from .voice_live import live_session
    @api.websocket('/live')
    async def live(ws:WebSocket):
        try:phone=device(ws.headers.get('authorization'))
        except HTTPException:await ws.close(code=4401);return
        engine=ws.query_params.get('engine',service.config.get('conversation_provider','live'))
        if engine=='realtime':
            from .voice_realtime import realtime_session
            await realtime_session(ws,service,phone)
        elif engine=='live':await live_session(ws,service,phone)
        else:await ws.close(code=4400)
    return api
