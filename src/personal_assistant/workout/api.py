"""Paired Companion and protected owner routes share the same workout engine."""
import re
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import Field
from .models import Model, Mutation
from .analytics import overview
from .imports import reconcile


class Sync(Model):
    operations: list[Mutation] = Field(min_length=1,max_length=100)


class Question(Model):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,100}$')
    text: str = Field(min_length=1,max_length=8000)
    photos: list[str] = Field(default_factory=list,max_length=6)
    photo_approval: bool = False
    context: dict = Field(default_factory=dict)


class Ready(Model):
    state: str = 'ready'
    detail: str = Field(default='',max_length=500)


class Lease(Model):
    token: str = Field(min_length=16,max_length=100)


class Answer(Lease):
    text: str = Field(min_length=1,max_length=24000)
    proposals: list[Mutation] = Field(default_factory=list,max_length=20)
    state: str = 'completed'
    assessment: dict | None = None


async def bounded(request, limit):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit: raise HTTPException(413,'Workout upload is too large')
    return bytes(raw)


def routers(store, submit, device=None):
    owner = APIRouter(prefix='/v1/workout',dependencies=[Depends(submit)])
    phone = APIRouter(prefix='/groceries/v1/mobile/workout',dependencies=[Depends(device)]) if device else None

    def install(router):
        @router.get('/changes')
        def changes(after: int=Query(default=0,ge=0),limit: int=Query(default=100,ge=1,le=200)):
            return store.changes(after,limit)

        @router.get('/entities')
        def entities(kind: str | None=None,offset: int=Query(default=0,ge=0),limit: int=Query(default=100,ge=1,le=200)):
            return store.list(kind,offset,limit)

        @router.get('/entities/{kind}/{identifier}')
        def entity(kind: str,identifier: str): return store.get(kind,identifier)

        @router.post('/sync')
        def sync(body: Sync): return {'results':store.mutate([m.model_dump() for m in body.operations])}

        @router.get('/overview')
        def summary(): return overview(store)

        @router.get('/export')
        def export(): return store.export()

        @router.post('/imports/{format}')
        async def import_file(format: str,request: Request,commit: bool=False,timezone: str='UTC'):
            return reconcile(store,await bounded(request,32*1024*1024),format,timezone,commit)

        @router.get('/imports/{digest}/original')
        def original(digest: str):
            return Response(store.original_import(digest),media_type='text/csv',
                            headers={'Content-Disposition':'attachment; filename="workout-source.csv"','Cache-Control':'private, no-store'})

        @router.put('/photos/{identity}')
        async def put_photo(identity: str,request: Request):
            if not re.fullmatch(r'[a-f0-9]{64}',identity): raise HTTPException(422,'Invalid photo checksum')
            return store.put_blob(identity,request.headers.get('content-type','').split(';')[0],await bounded(request,8*1024*1024))

        @router.get('/photos/{identity}')
        def get_photo(identity: str):
            mime,body = store.blob(identity)
            return Response(body,media_type=mime,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

        @router.get('/trainer/conversation')
        def conversation(limit: int=Query(default=100,ge=1,le=200),before: float | None=None):
            return {'items':store.conversation(limit,before),'status':store.status()}

        @router.post('/trainer/questions')
        def question(body: Question):
            return store.question(body.id,body.text,body.photos,body.photo_approval,body.context)

        @router.post('/trainer/{identifier}/approve')
        def approve(identifier: str): return store.approve(identifier)

    install(owner)
    if phone: install(phone)

    @owner.put('/trainer/heartbeat')
    def heartbeat(body: Ready):
        store.heartbeat(body.state,body.detail)
        return store.status()

    @owner.post('/trainer/claim')
    def claim(): return {'job':store.claim()}

    @owner.post('/trainer/{identifier}/renew')
    def renew(identifier: str,body: Lease):
        store.renew(identifier,body.token)
        return {'ok':True}

    @owner.put('/trainer/{identifier}/answer')
    def answer(identifier: str,body: Answer):
        store.finish(identifier,body.token,body.text,[p.model_dump() for p in body.proposals],body.state,body.assessment)
        return {'ok':True}

    return [owner,phone] if phone else [owner]
