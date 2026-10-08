"""Scoped companion pairing and durable phone-action delivery."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Devices:
    def __init__(self,path,clock=time.time):
        self.path=Path(path);self.clock=clock
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS pairing(hash TEXT PRIMARY KEY,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS phones(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,name TEXT NOT NULL,created REAL NOT NULL,seen REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS phone_actions(id TEXT PRIMARY KEY,phone TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,state TEXT NOT NULL,result TEXT);
            ''')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
        try: yield db;db.commit()
        except BaseException: db.rollback();raise
        finally: db.close()

    def pairing(self):
        code=secrets.token_urlsafe(24)
        with self.db() as db:
            db.execute('DELETE FROM pairing WHERE expires<?',(self.clock(),))
            db.execute('INSERT INTO pairing VALUES(?,?)',(digest(code),self.clock()+600))
        return {'code':code,'expires_in':600}

    def exchange(self,code,name):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT expires FROM pairing WHERE hash=?',(digest(code),)).fetchone()
            if not row or row['expires']<=self.clock(): raise ValueError('Pairing code expired or already used.')
            db.execute('DELETE FROM pairing WHERE hash=?',(digest(code),))
            token='pa_mobile_'+secrets.token_urlsafe(32);identifier=secrets.token_hex(16)
            db.execute('INSERT INTO phones(id,token_hash,name,created,seen) VALUES(?,?,?,?,?)',(identifier,digest(token),name,self.clock(),self.clock()))
            return {'token':token,'id':identifier}

    def authenticate(self,token):
        with self.db() as db:
            row=db.execute('SELECT id FROM phones WHERE token_hash=? AND revoked=0',(digest(token),)).fetchone()
            if not row: raise ValueError('Companion disconnected. Pair again.')
            db.execute('UPDATE phones SET seen=? WHERE id=?',(self.clock(),row['id']))
            return row['id']

    def phones(self):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT id,name,seen,revoked FROM phones ORDER BY created DESC')]

    def revoke(self,identifier):
        with self.db() as db: db.execute('UPDATE phones SET revoked=1 WHERE id=?',(identifier,))

    def enqueue(self,identifier,phone,body):
        encoded=json.dumps(body,sort_keys=True)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM phone_actions WHERE id=?',(identifier,)).fetchone()
            if old:
                if old['phone']!=phone or old['body']!=encoded: raise ValueError('Action ID already used for different alarm.')
                return dict(old),False
            if not db.execute('SELECT id FROM phones WHERE id=? AND revoked=0',(phone,)).fetchone(): raise ValueError('Install and pair the phone companion first.')
            db.execute('INSERT INTO phone_actions VALUES(?,?,?,?,?,?,NULL)',(identifier,phone,encoded,self.clock(),self.clock()+600,'queued'))
            return dict(db.execute('SELECT * FROM phone_actions WHERE id=?',(identifier,)).fetchone()),True

    def pending(self,phone):
        with self.db() as db:
            db.execute("UPDATE phone_actions SET state='expired' WHERE state='queued' AND expires<=?",(self.clock(),))
            return [{**dict(row),'body':json.loads(row['body'])} for row in db.execute("SELECT * FROM phone_actions WHERE phone=? AND state='queued' ORDER BY created",(phone,))]

    def receipt(self,phone,identifier,state):
        with self.db() as db:
            row=db.execute('SELECT * FROM phone_actions WHERE phone=? AND id=?',(phone,identifier)).fetchone()
            if not row: raise ValueError('Phone action not found.')
            if row['state'] not in ('queued',state): raise ValueError('Action already has a different outcome.')
            if row['expires']<=self.clock() and row['state']=='queued': raise ValueError('Alarm request expired.')
            db.execute('UPDATE phone_actions SET state=?,result=? WHERE phone=? AND id=?',(state,json.dumps({'clock_registration_verified':False}),phone,identifier))
            return {'state':state,'clock_registration_verified':False}

    def action(self,identifier):
        with self.db() as db:
            row=db.execute('SELECT * FROM phone_actions WHERE id=?',(identifier,)).fetchone()
            if not row:raise ValueError('Phone action not found.')
            data=dict(row)
            if data['state']=='queued' and data['expires']<=self.clock():
                db.execute("UPDATE phone_actions SET state='expired' WHERE id=?",(identifier,));data['state']='expired'
            data['body']=json.loads(data['body']);data['clock_registration_verified']=False
            return data


class Exchange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code:str=Field(min_length=20,max_length=100)
    name:str=Field(default='Android',max_length=100)


class Alarm(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    phone:str=Field(min_length=1,max_length=64)
    hour:int=Field(ge=0,le=23)
    minute:int=Field(ge=0,le=59)
    label:str=Field(default='Alarm',max_length=200)
    launch:bool=False


class Receipt(BaseModel):
    state:str=Field(pattern=r'^(delegated|failed)$')


class ImportPreview(BaseModel):
    content:str=Field(min_length=1,max_length=10000)


class PublishedRelease(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    version_code:int=Field(ge=1)
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')


def mobile_router(store,owner_auth,grocery_store,change,sender=None,apk=None):
    api=APIRouter(prefix='/v1/mobile')
    api.release_pump=None
    api.release_feed=None
    def device(authorization:str|None=Header(default=None)):
        if not authorization or not authorization.startswith('Bearer pa_mobile_'): raise HTTPException(401,'Pair the companion app.')
        try:return store.authenticate(authorization[7:])
        except ValueError as error:raise HTTPException(401,str(error)) from None
    @api.post('/pairing',dependencies=[Depends(owner_auth)])
    def pair():return store.pairing()
    @api.post('/exchange')
    def exchange(body:Exchange):return store.exchange(body.code,body.name)
    @api.get('/phones',dependencies=[Depends(owner_auth)])
    def phones():return store.phones()
    @api.post('/phones/{identifier}/revoke',dependencies=[Depends(owner_auth)])
    def revoke(identifier:str):store.revoke(identifier);return {'revoked':True}
    @api.get('/list')
    def snapshot(phone=Depends(device)):return grocery_store.snapshot()
    @api.post('/mutations')
    def mutation(body:dict,phone=Depends(device)):
        from .api import Mutation
        value=Mutation.model_validate(body)
        if value.operation=='recipe_save' and value.recipe is None:raise HTTPException(422,'A recipe is required.')
        return change(value.model_dump(exclude_none=True))
    @api.post('/recipes/import/preview')
    def recipe_preview(body:ImportPreview,phone=Depends(device)):
        from .recipes import preview_import
        return preview_import(body.content)
    @api.get('/actions')
    def actions(phone=Depends(device)):return store.pending(phone)
    @api.post('/actions/{identifier}/receipt')
    def receipt(identifier:str,body:Receipt,phone=Depends(device)):return store.receipt(phone,identifier,body.state)
    @api.post('/alarms',dependencies=[Depends(owner_auth)])
    def alarm(body:Alarm):
        action,created=store.enqueue(body.id,body.phone,{'type':'alarm','hour':body.hour,'minute':body.minute,'label':body.label})
        accepted=False
        if sender and action['state']=='queued':
            if body.launch:
                payload={'message':'command_activity','data':{'phone_id':body.phone,'action_id':body.id,'intent_action':'android.intent.action.VIEW','intent_uri':'personalassistant://sync','intent_package_name':'com.personalassistant.companion','ttl':600,'priority':'high'}}
            else:
                payload={'title':'Phone alarm request','message':f'{body.hour:02}:{body.minute:02} · {body.label}',
                    'data':{'phone_id':body.phone,'action_id':body.id,'tag':'assistant-alarm-'+body.id,'clickAction':'deep-link://personalassistant://sync','ttl':600,'priority':'high','actions':[{'action':'URI','title':'Set alarm','uri':'deep-link://personalassistant://sync'}]}}
            try:sender(payload);accepted=True
            except OSError:pass
        return {'id':body.id,'created':created,'state':action['state'],'push_api_accepted':accepted,'clock_registration_verified':False}
    @api.get('/alarms/{identifier}',dependencies=[Depends(owner_auth)])
    def alarm_status(identifier:str):return store.action(identifier)
    if apk:
        from .releases import ReleaseFeed,CompanionReleasePump
        feed=ReleaseFeed(apk)
        api.release_feed=feed
        api.release_pump=CompanionReleasePump(feed,sender) if sender else None
        @api.get('/release')
        def release():
            try:return feed.manifest()
            except FileNotFoundError as error:raise HTTPException(404,str(error)) from None
            except ValueError as error:raise HTTPException(503,str(error)) from None
        @api.post('/release/published',dependencies=[Depends(owner_auth)])
        def published(body:PublishedRelease):
            try:result=feed.publish(body.version_code,body.sha256)
            except FileNotFoundError as error:raise HTTPException(404,str(error)) from None
            except ValueError as error:raise HTTPException(409,str(error)) from None
            return {**result,'push_configured':sender is not None,'handset_delivery_verified':False}
        @api.get('/release/status',dependencies=[Depends(owner_auth)])
        def release_status():
            try:current=feed.manifest()
            except (FileNotFoundError,ValueError) as error:raise HTTPException(503,str(error)) from None
            return {**feed.status(current['version_code']),'push_configured':sender is not None,'handset_delivery_verified':False}
        @api.get('/companion.apk')
        def download():
            if not Path(apk).is_file():raise HTTPException(404,'Companion build not available.')
            return FileResponse(apk,media_type='application/vnd.android.package-archive',filename='assistant-companion.apk',headers={'Cache-Control':'no-store'})
    return api
