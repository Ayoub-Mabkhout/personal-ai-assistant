"""Durable new instructions for an existing headless task session."""
from datetime import datetime,timezone
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .store import Conflict


class Followup(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    instruction:str=Field(min_length=1,max_length=4096)

    @field_validator('instruction')
    @classmethod
    def not_blank(cls,value):
        if not value.strip():raise ValueError('Enter an instruction.')
        return value


class Continuations:
    def __init__(self,queue):
        self.queue=queue;self.path=queue.path.with_name('task-continuations.sqlite3')
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY,root TEXT NOT NULL,fingerprint TEXT NOT NULL,payload TEXT NOT NULL,accepted INTEGER NOT NULL DEFAULT 0)')
        # Identical queue envelopes recover both sides of a crash during submit.
        with self.connection() as db:rows=db.execute('SELECT id,payload FROM turns WHERE accepted=0 ORDER BY rowid').fetchall()
        for identifier,encoded in rows:
            self.queue.submit(json.loads(encoded),source='task_continuation');self.accepted(identifier)

    def accepted(self,identifier):
        with self.connection() as db:db.execute('UPDATE turns SET accepted=1 WHERE id=?',(identifier,))

    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=15)
        try:
            with db:yield db
        finally:db.close()

    def root(self,identifier):
        job=self.queue.get(identifier)
        root=(job['payload'].get('resume_task') or {}).get('root_id',identifier)
        return self.queue.get(root)

    def accept(self,identifier,body):
        root=self.root(identifier);root_id=root['id']
        digest=hashlib.sha256(json.dumps([root_id,body.instruction],ensure_ascii=False).encode()).hexdigest()
        child='continue-'+hashlib.sha256(body.id.encode()).hexdigest()[:48]
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT fingerprint,payload FROM turns WHERE id=?',(body.id,)).fetchone()
            if row:
                if row[0]!=digest:raise Conflict('This follow-up ID already has different content.')
                payload=json.loads(row[1])
            else:
                payload={'id':child,'command':body.instruction,'timezone':root['payload']['timezone'],
                         'created_at':datetime.fromtimestamp(self.queue.clock(),timezone.utc).isoformat(),
                         'expires_at':None,'resume_task':{'root_id':root_id},
                         'workspace':root['payload'].get('workspace')}
                db.execute('INSERT INTO turns(id,root,fingerprint,payload) VALUES(?,?,?,?)',(body.id,root_id,digest,json.dumps(payload)))
        job,created=self.queue.submit(payload,source='task_continuation');self.accepted(body.id)
        return job,created

    def turns(self,identifier):
        root=self.root(identifier)
        with self.connection() as db:rows=db.execute('SELECT payload FROM turns WHERE root=? ORDER BY rowid',(root['id'],)).fetchall()
        return [self.queue.get(json.loads(row[0])['id']) for row in rows]
