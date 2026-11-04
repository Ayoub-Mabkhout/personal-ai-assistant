"""Durable readable-answer snapshots, fenced by the existing execution lease."""
import hashlib
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from .store import Conflict, Missing


class Snapshot(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    token:str=Field(min_length=16,max_length=200)
    sequence:int=Field(ge=0)
    text:str=Field(max_length=24000)


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS answer_streams(
        scope TEXT NOT NULL,job TEXT NOT NULL,attempt TEXT NOT NULL,
        sequence INTEGER NOT NULL,text TEXT NOT NULL,revision INTEGER NOT NULL,
        updated REAL NOT NULL,PRIMARY KEY(scope,job))''')


def read_many(db,scope,identifiers):
    identifiers=list(dict.fromkeys(identifiers))
    if not identifiers:return {}
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='answer_streams'").fetchone():return {}
    marks=','.join('?' for _ in identifiers)
    return {row[0]:{'partial_answer':row[1],'partial_revision':row[2]}
            for row in db.execute('SELECT job,text,revision FROM answer_streams WHERE scope=? AND job IN ('+marks+')',
                                  [scope,*identifiers])}


def write(db,scope,identifier,body,now):
    initialize(db)
    attempt=hashlib.sha256(body.token.encode()).hexdigest()
    old=db.execute('SELECT attempt,sequence,text,revision FROM answer_streams WHERE scope=? AND job=?',
                   (scope,identifier)).fetchone()
    if old and old[0]==attempt:
        if body.sequence<old[1]:return {'revision':old[3]}
        if body.sequence==old[1]:
            if body.text!=old[2]:raise Conflict('Stream sequence already has different content')
            return {'revision':old[3]}
    elif body.sequence!=0:
        raise Conflict('Start this answer stream before publishing text')
    revision=(old[3] if old else 0)+1
    db.execute('INSERT OR REPLACE INTO answer_streams VALUES(?,?,?,?,?,?,?)',
               (scope,identifier,attempt,body.sequence,body.text,revision,now))
    return {'revision':revision}


def queue_snapshot(queue,identifier,body):
    with queue.connection(True) as db:
        row=queue.owned(db,identifier,body.token)
        root=(json.loads(row['payload']).get('resume_task') or {}).get('root_id') or identifier
        result=write(db,'agent',identifier,body,queue.clock())
    queue.wakeups.notify(('answer',identifier))
    queue.wakeups.notify(('answer',root))
    return result


def coach_snapshot(store,identifier,body):
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT 1 FROM trainer WHERE user_id=? AND id=? AND state='running' AND token=? AND lease_until>?",
                       (store.user_id,identifier,body.token,store.clock())).fetchone()
        if not row:raise Conflict('Coach lease is no longer current')
        result=write(db,'coach:'+store.user_id,identifier,body,store.clock())
        store.wake(db,'conversation')
    return result


def money_snapshot(store,identifier,body):
    # Money is a single trusted owner-writer pipeline. Its API has no cloud execution lease.
    with store.db() as db:
        row=db.execute('SELECT answer FROM conversations WHERE id=?',(identifier,)).fetchone()
        if not row:raise Missing('Conversation not found')
        if row[0] is not None:raise Conflict('Conversation already answered')
        result=write(db,'money',identifier,body,store.clock())
    store.stream_wakeups.notify('conversation')
    return result


def router(queue,worker):
    api=APIRouter(prefix='/v1/agent/worker',dependencies=[Depends(worker)])
    @api.put('/{identifier}/stream')
    def progress(identifier:str,body:Snapshot):return queue_snapshot(queue,identifier,body)
    return api
