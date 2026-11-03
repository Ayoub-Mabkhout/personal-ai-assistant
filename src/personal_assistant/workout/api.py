"""Paired Companion and protected owner routes share the same workout engine."""
import re
from datetime import date
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


class Extension(Model):
    end: date
    base_revision: int = Field(ge=0)
    mutation_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,100}$')


class Lease(Model):
    token: str = Field(min_length=16,max_length=100)


class CoachTimings(Model):
    """Seconds after the coach received its claim, on the coach's own clock (no clock-skew issues)."""
    model_started_after: float | None = Field(default=None,ge=0,le=86400)
    first_output_after: float | None = Field(default=None,ge=0,le=86400)
    first_text_after: float | None = Field(default=None,ge=0,le=86400)
    model_finished_after: float | None = Field(default=None,ge=0,le=86400)


class Answer(Lease):
    text: str = Field(min_length=1,max_length=24000)
    proposals: list[Mutation] = Field(default_factory=list,max_length=20)
    state: str = 'completed'
    assessment: dict | None = None
    timings: CoachTimings | None = None


async def bounded(request, limit):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit: raise HTTPException(413,'Workout upload is too large')
    return bytes(raw)


def routers(store, submit, device=None):
    owner = APIRouter(prefix='/v1/workout',dependencies=[Depends(submit)])
    phone = APIRouter(prefix='/groceries/v1/mobile/workout',dependencies=[Depends(device)]) if device else None

    def get_store(): return store

    install(owner, get_store)
    if phone: install(phone, get_store)

    install_worker(owner, get_store)
    return [owner,phone] if phone else [owner]


def install(router, get_store, *, browser=False):
    @router.get('/changes')
    def changes(after: int=Query(default=0,ge=0),limit: int=Query(default=100,ge=1,le=200), store=Depends(get_store)):
        return store.changes(after,limit)

    @router.get('/entities')
    def entities(kind: str | None=None,offset: int=Query(default=0,ge=0),limit: int=Query(default=100,ge=1,le=200), store=Depends(get_store)):
        return store.list(kind,offset,limit)

    @router.get('/entities/{kind}/{identifier}')
    def entity(kind: str,identifier: str, store=Depends(get_store)): return store.get(kind,identifier)

    @router.post('/sync')
    def sync(body: Sync, store=Depends(get_store)): return {'results':store.mutate([m.model_dump() for m in body.operations])}

    @router.get('/overview')
    def summary(store=Depends(get_store)):
        if not store.status()['available']:
            store.prepare_brief()
        return {**overview(store), 'scheduled_sprints': store.scheduled_sprints_enabled()}

    @router.post('/sprints/{identifier}/extend')
    def extend_sprint(identifier: str,body: Extension, store=Depends(get_store)):
        from .programs import extend
        return extend(store,identifier,body.end,body.base_revision,body.mutation_id)

    @router.get('/export')
    def export(store=Depends(get_store)): return store.export()

    @router.post('/imports/{format}')
    async def import_file(format: str,request: Request,commit: bool=False,timezone: str='UTC', store=Depends(get_store)):
        return reconcile(store,await bounded(request,32*1024*1024),format,timezone,commit)

    @router.get('/imports/{digest}/original')
    def original(digest: str, store=Depends(get_store)):
        return Response(store.original_import(digest),media_type='text/csv',
                        headers={'Content-Disposition':'attachment; filename="workout-source.csv"','Cache-Control':'private, no-store'})

    @router.put('/photos/{identity}')
    async def put_photo(identity: str,request: Request, store=Depends(get_store)):
        if not re.fullmatch(r'[a-f0-9]{64}',identity): raise HTTPException(422,'Invalid photo checksum')
        return store.put_blob(identity,request.headers.get('content-type','').split(';')[0],await bounded(request,8*1024*1024))

    @router.get('/photos/{identity}')
    def get_photo(identity: str, store=Depends(get_store)):
        mime,body = store.blob(identity)
        return Response(body,media_type=mime,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    @router.get('/trainer/conversation')
    async def conversation(request: Request, limit: int=Query(default=100,ge=1,le=200),before: float | None=None,
                           wait: float=Query(default=0,ge=0), since: str | None=Query(default=None,max_length=64),
                           store=Depends(get_store)):
        """With ?since=<version>&wait=N, hold the request until the chat changes (or N seconds pass)."""
        from personal_assistant.relay.wakeups import long_poll, requested_wait
        from starlette.concurrency import run_in_threadpool
        seconds = requested_wait(wait) if since else 0
        def changed():
            current = store.conversation_view(limit, before)
            return current if not seconds or current['version'] != since else None
        view, seconds = await long_poll(changed, store.wakeups, ('conversation', store.user_id), seconds, request, recheck=15)
        if view is None:  # timed out unchanged: answer with the current (same-version) view
            view = await run_in_threadpool(store.conversation_view, limit, before)
        return {**view, 'wait_seconds': seconds}

    @router.post('/trainer/questions')
    def question(body: Question, store=Depends(get_store)):
        context = body.context
        if browser:
            context = {key: context[key] for key in ('current_workout_id', 'sprint_id', 'template_id') if key in context}
        return store.question(body.id,body.text,body.photos,body.photo_approval,context)

    @router.post('/trainer/{identifier}/approve')
    def approve(identifier: str, store=Depends(get_store)): return store.approve(identifier)


def install_worker(owner, get_store):
    @owner.put('/trainer/heartbeat')
    def heartbeat(body: Ready, store=Depends(get_store)):
        store.heartbeat(body.state,body.detail)
        return store.status()

    @owner.post('/trainer/claim')
    async def claim(request: Request, wait: float=Query(default=0,ge=0), store=Depends(get_store)):
        """?wait=N (max 25) holds the request until a job is queued for this athlete or N seconds pass."""
        from personal_assistant.relay.wakeups import long_poll, requested_wait
        job, waited = await long_poll(store.claim, store.wakeups, ('trainer', store.user_id), requested_wait(wait), request)
        return {'job':job,'wait_seconds':waited}

    @owner.post('/trainer/prepare-brief')
    def prepare_brief(timezone: str='UTC', store=Depends(get_store)): return store.prepare_brief(timezone)

    @owner.post('/trainer/{identifier}/renew')
    def renew(identifier: str,body: Lease, store=Depends(get_store)):
        store.renew(identifier,body.token)
        return {'ok':True}

    @owner.put('/trainer/{identifier}/answer')
    def answer(identifier: str,body: Answer, store=Depends(get_store)):
        store.finish(identifier,body.token,body.text,[p.model_dump() for p in body.proposals],body.state,body.assessment,
                     body.timings.model_dump(exclude_none=True) if body.timings else None)
        return {'ok':True}
