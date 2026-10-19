"""Paired phone uploads retained with tasks; workers download verified originals."""
from contextlib import contextmanager
import hashlib
import base64
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from .file_drops import clean_name, MIME

ID=r'^[A-Za-z0-9_-]{8,64}$'
MAX_FILE=25*1024*1024
MAX_FILES=10


class TaskAttachments:
    def __init__(self, path, directory, clock=time.time):
        self.path,self.directory,self.clock=Path(path),Path(directory),clock
        self.directory.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS attachments(
                id TEXT PRIMARY KEY,phone TEXT NOT NULL,name TEXT NOT NULL,mime TEXT NOT NULL,
                size INTEGER NOT NULL,sha256 TEXT NOT NULL,ready INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attachment_tasks(id TEXT NOT NULL,task TEXT NOT NULL,PRIMARY KEY(id,task));''')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def reserve(self, identifier, phone, value):
        if not re.fullmatch(ID,identifier):raise HTTPException(422,'Invalid attachment ID.')
        if set(value)!={'name','mime','size','sha256'}:raise HTTPException(422,'Invalid attachment manifest.')
        try:name=clean_name(value['name'])
        except ValueError as error:raise HTTPException(422,str(error)) from None
        if len(name.encode('utf-8'))>160:raise HTTPException(422,'Attachment file name is too long.')
        mime,size,digest=value['mime'],value['size'],value['sha256']
        if type(size) is not int or not 0<=size<=MAX_FILE:raise HTTPException(413,'Attachments can be up to 25 MB each.')
        if not isinstance(mime,str) or not MIME.fullmatch(mime) or not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest):raise HTTPException(422,'Invalid attachment metadata.')
        with self.db() as db:
            old=db.execute('SELECT * FROM attachments WHERE id=?',(identifier,)).fetchone()
            if old:
                if (old['phone'],old['name'],old['mime'],old['size'],old['sha256'])!=(phone,name,mime,size,digest):raise HTTPException(409,'Attachment ID already has different contents.')
                return dict(old)
            if db.execute('SELECT COALESCE(SUM(size),0) FROM attachments').fetchone()[0]+size>1024*1024*1024:raise HTTPException(507,'Task attachment storage is full.')
            db.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?,0,?)',(identifier,phone,name,mime,size,digest,self.clock()))
        return {'id':identifier,'phone':phone,'name':name,'mime':mime,'size':size,'sha256':digest,'ready':0}

    def get(self, identifier, phone=None, associated=False):
        if not re.fullmatch(ID,identifier):raise HTTPException(404,'Attachment not found.')
        with self.db() as db:
            row=db.execute('SELECT * FROM attachments WHERE id=? AND ready=1',(identifier,)).fetchone()
            linked=db.execute('SELECT 1 FROM attachment_tasks WHERE id=?',(identifier,)).fetchone()
        if not row or phone is not None and row['phone']!=phone and not linked or associated and not linked:raise HTTPException(404,'Attachment not found.')
        return {k:row[k] for k in ('id','name','mime','size','sha256')}

    def bind(self, identifiers, task, phone=None):
        if len(identifiers)>MAX_FILES or len(set(identifiers))!=len(identifiers):raise HTTPException(422,'Choose up to 10 distinct attachments.')
        with self.db() as db:
            for identifier in identifiers:
                row=db.execute('SELECT * FROM attachments WHERE id=? AND ready=1',(identifier,)).fetchone()
                if not row or phone is not None and row['phone']!=phone:raise HTTPException(404,'An attachment has not finished uploading.')
            for identifier in identifiers:db.execute('INSERT OR IGNORE INTO attachment_tasks VALUES(?,?)',(identifier,task))

    def describe(self, identifiers):
        return [self.get(identifier) for identifier in identifiers]


def attachment_router(store, device, tokens):
    api=APIRouter()
    def worker(authorization:str|None=Header(default=None)):
        if not authorization or not any(secrets.compare_digest(authorization,'Bearer '+token) for token in tokens):raise HTTPException(401,'Authentication required.')

    @api.put('/groceries/v1/mobile/task-attachments/{identifier}')
    async def upload(identifier:str,request:Request,phone=Depends(device),x_attachment_manifest:str=Header(default='')):
        try:
            if len(x_attachment_manifest)>8192:raise ValueError()
            value=json.loads(base64.b64decode(x_attachment_manifest,validate=True))
        except (ValueError,UnicodeDecodeError):raise HTTPException(422,'Attachment manifest required.') from None
        if not isinstance(value,dict):raise HTTPException(422,'Attachment manifest required.')
        row=store.reserve(identifier,phone,value)
        if row['ready']:return store.get(identifier,phone)
        fd,name=tempfile.mkstemp(prefix='upload-',dir=store.directory);digest=hashlib.sha256();size=0
        try:
            with os.fdopen(fd,'wb') as output:
                async for piece in request.stream():
                    size+=len(piece)
                    if size>row['size'] or size>MAX_FILE:raise HTTPException(413,'Upload exceeds the declared file size.')
                    digest.update(piece);output.write(piece)
            if size!=row['size'] or digest.hexdigest()!=row['sha256']:raise HTTPException(422,'Attachment checksum or size did not match.')
            os.replace(name,store.directory/identifier)
            with store.db() as db:db.execute('UPDATE attachments SET ready=1 WHERE id=?',(identifier,))
        finally:
            Path(name).unlink(missing_ok=True)
        return store.get(identifier,phone)

    @api.get('/groceries/v1/mobile/task-attachments/{identifier}')
    def metadata(identifier:str,phone=Depends(device)):return store.get(identifier,phone)

    @api.get('/groceries/v1/mobile/task-attachments/{identifier}/content')
    def phone_file(identifier:str,phone=Depends(device)):
        row=store.get(identifier,phone)
        return FileResponse(store.directory/identifier,media_type=row['mime'],filename=row['name'],headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    @api.get('/v1/agent/attachments/{identifier}',dependencies=[Depends(worker)])
    def worker_metadata(identifier:str):return store.get(identifier,associated=True)

    @api.get('/v1/agent/attachments/{identifier}/content',dependencies=[Depends(worker)])
    def worker_file(identifier:str):
        row=store.get(identifier,associated=True)
        return FileResponse(store.directory/identifier,media_type=row['mime'],filename=row['name'],headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
    return api
