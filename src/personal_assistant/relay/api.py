"""Relay API. Service credentials are distinct from Home Assistant user login."""

import os
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .store import Conflict, Missing, Queue


class BodyLimit:
    def __init__(self, app, limit=16384):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or (scope.get('path')=='/companion/v1/releases/artifact' and scope.get('method')=='PUT'):
            return await self.app(scope, receive, send)
        body = bytearray()
        path=scope.get('path','')
        limit = 4*1024*1024 if path=='/groceries/v1/mobile/voice' else (5*1024*1024 if path=='/v1/calendar/reminders/snapshot' else (
            1024*1024 if path in ('/groceries/v1/recipes/import/preview','/groceries/v1/recipes/import/commit') else self.limit))
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > limit:
                return await JSONResponse({'detail': 'Request is too large.'}, status_code=413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    command: str = Field(min_length=1, max_length=4096)
    timezone: str = Field(min_length=1, max_length=100)
    created_at: str | None = None
    expires_at: str | None = None


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra='forbid')
    readiness: Literal['ready', 'blocked']


class AgentPrompt(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    prompt: str = Field(min_length=1,max_length=4096)
    timezone: str = Field(default='Europe/Berlin',max_length=100)
    created_at: str | None = None
    expires_at: str | None = None
    workspace: str | None = Field(default=None,max_length=1000)


class Lease(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    lease_seconds: int = Field(default=60, ge=15, le=300)


class Renew(Lease):
    lease_token: str


class Result(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lease_token: str
    state: Literal['completed', 'failed', 'needs_input']
    result: dict


def create_app(path, submit_token, worker_token, clock=None, groceries=None, notifications=None,task_links=None,voice=None,release_publish_token_file=None):
    if len(submit_token) < 32 or len(worker_token) < 32 or submit_token == worker_token:
        raise ValueError('Use distinct service tokens of at least 32 characters.')
    queue = Queue(path, notifications=bool(notifications), **({'clock': clock} if clock else {}))
    agent_queue = Queue(Path(path).with_name('agent-queue.sqlite3'), serial=True, notifications=bool(notifications),
                        **({'clock':clock} if clock else {}))
    pump=None; reminder_pump=None; sender=None; release_pump=None; native_pump=None; mobile_events=None
    if groceries:
        from personal_assistant.groceries.mobile import Devices
        from .mobile_push import MobileEventStore,MobilePushPump,FcmPush
        mobile_events=MobileEventStore(Devices(Path(groceries['path']).with_name('phones.sqlite3'),**({'clock':clock} if clock else {})))
        push_config=(notifications or {}).get('companion_push')
        native_provider=(notifications or {}).get('native_provider') or (FcmPush(push_config) if push_config else None)
        native_pump=MobilePushPump(mobile_events,native_provider)
    if notifications:
        from .notifications import HomeAssistantPush,NotificationPump
        if notifications.get('provider')=='companion':
            if not mobile_events:raise ValueError('Native notifications require Companion pairing.')
            from .mobile_push import CompanionSender
            sender=CompanionSender(mobile_events)
        else:sender=notifications.get('sender') or HomeAssistantPush(notifications)
        pump=NotificationPump({'command':queue,'agent':agent_queue},sender,notifications['public_url'],
            visibility=notifications.get('visibility','private'),task_links=task_links)
        from .reminders import ReminderStore,ReminderPump
        reminder_store=ReminderStore(Path(path).with_name('reminders.sqlite3'),**({'clock':clock} if clock else {}))
        reminder_pump=ReminderPump(reminder_store,sender,visibility=notifications.get('visibility','private'))
    @asynccontextmanager
    async def lifespan(app):
        if pump: pump.start()
        if reminder_pump: reminder_pump.start()
        if release_pump: release_pump.start()
        if native_pump: native_pump.start()
        try: yield
        finally:
            if pump: pump.close()
            if reminder_pump: reminder_pump.close()
            if release_pump: release_pump.close()
            if native_pump: native_pump.close()
    app = FastAPI(title='Personal assistant relay', docs_url=None, redoc_url=None, openapi_url=None,lifespan=lifespan)
    app.state.notification_pump=pump
    app.state.native_push_pump=native_pump
    app.state.mobile_events=mobile_events
    app.add_middleware(BodyLimit)
    if groceries:
        from personal_assistant.groceries.api import router
        groceries_api=router(**groceries,phone_sender=sender)
        app.include_router(groceries_api)
        release_pump=groceries_api.release_pump
        app.state.release_feed=groceries_api.release_feed
        if release_publish_token_file:
            from .release_upload import release_upload_router
            app.include_router(release_upload_router(groceries_api.release_feed,release_publish_token_file))
        if voice is not None:
            from .voice import VoiceService,voice_router
            from personal_assistant.groceries.store import Groceries
            voice_service=VoiceService(Path(path).with_name('voice.sqlite3'),groceries_api.devices,
                Groceries(groceries['path']),agent_queue,queue,config=voice)
            app.state.voice=voice_service
            app.include_router(voice_router(voice_service))
        from .tasks import task_router
        app.include_router(task_router({'command':queue,'agent':agent_queue},groceries['ha_url'],
            Path(groceries['assets']).parent/'tasks',task_links=task_links))
        from .mobile_tasks import mobile_task_router
        from .mobile_push import mobile_push_router
        app.include_router(mobile_task_router(groceries_api.devices,{'command':queue,'agent':agent_queue}))
        app.include_router(mobile_push_router(mobile_events))

    def authorization(expected):
        def verify(authorization: str | None = Header(default=None)):
            if not authorization or not secrets.compare_digest(authorization.encode(), ('Bearer ' + expected).encode()):
                raise HTTPException(401, 'Authentication required.', headers={'WWW-Authenticate': 'Bearer'})
        return verify
    submit = authorization(submit_token)
    worker = authorization(worker_token)
    from .replies import reply_router
    app.include_router(reply_router({'command':queue,'agent':agent_queue},submit))
    if reminder_pump:
        from .reminders import reminder_router
        app.include_router(reminder_router(reminder_store,submit,worker))

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409)

    @app.exception_handler(Missing)
    async def missing(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    @app.get('/healthz')
    def health():
        with queue.connection() as db:
            db.execute('SELECT 1').fetchone()
        return {'ok': True}

    @app.get('/v1/status', dependencies=[Depends(submit)])
    def status():
        return queue.status()

    @app.post('/v1/commands', dependencies=[Depends(submit)])
    def add(command: Command):
        job, created = queue.submit(command.model_dump())
        return JSONResponse({'job': job, 'created': created, 'connection': queue.status(),
            'notifications':{'enabled':bool(notifications)}}, status_code=201 if created else 200)

    @app.get('/v1/commands/{request_id}', dependencies=[Depends(submit)])
    def get(request_id: str):
        return queue.get(request_id)

    @app.get('/v1/commands/{request_id}/history', dependencies=[Depends(submit)])
    def history(request_id: str):
        return queue.history(request_id)

    @app.post('/v1/commands/{request_id}/cancel', dependencies=[Depends(submit)])
    def cancel(request_id: str):
        return queue.cancel(request_id)

    @app.get('/v1/agent/status', dependencies=[Depends(submit)])
    def agent_status():
        return agent_queue.status()

    @app.post('/v1/agent/prompts', dependencies=[Depends(submit)])
    def add_agent_prompt(value:AgentPrompt):
        payload=value.model_dump()
        payload['command']=payload.pop('prompt')
        job,created=agent_queue.submit(payload,source='agent_prompt')
        return JSONResponse({'job':job,'created':created,'connection':agent_queue.status(),
            'notifications':{'enabled':bool(notifications)}},status_code=201 if created else 200)

    @app.get('/v1/agent/prompts/{request_id}', dependencies=[Depends(submit)])
    def get_agent_prompt(request_id:str):
        return agent_queue.get(request_id)

    @app.get('/v1/agent/prompts/{request_id}/history', dependencies=[Depends(submit)])
    def agent_history(request_id:str):
        return agent_queue.history(request_id)

    @app.post('/v1/agent/prompts/{request_id}/cancel', dependencies=[Depends(submit)])
    def cancel_agent(request_id:str):
        return agent_queue.cancel(request_id)

    @app.post('/v1/agent/prompts/{request_id}/notify', dependencies=[Depends(submit)])
    def notify_agent(request_id:str):
        return agent_queue.notify_again(request_id)

    @app.post('/v1/commands/{request_id}/notify', dependencies=[Depends(submit)])
    def notify_command(request_id:str):
        return queue.notify_again(request_id)

    @app.post('/v1/agent/worker/heartbeat', dependencies=[Depends(worker)])
    def agent_heartbeat(value:Heartbeat):
        return agent_queue.heartbeat(value.readiness)

    @app.post('/v1/agent/worker/claim', dependencies=[Depends(worker)])
    def agent_claim(value:Lease):
        return {'job':agent_queue.claim(value.lease_seconds)}

    @app.post('/v1/agent/worker/{request_id}/renew', dependencies=[Depends(worker)])
    def agent_renew(request_id:str,value:Renew):
        return agent_queue.renew(request_id,value.lease_token,value.lease_seconds)

    @app.post('/v1/agent/worker/{request_id}/result', dependencies=[Depends(worker)])
    def agent_result(request_id:str,value:Result):
        return agent_queue.finish(request_id,value.lease_token,value.state,value.result)

    @app.post('/v1/worker/heartbeat', dependencies=[Depends(worker)])
    def heartbeat(value: Heartbeat):
        return queue.heartbeat(value.readiness)

    @app.post('/v1/worker/claim', dependencies=[Depends(worker)])
    def claim(value: Lease):
        return {'job': queue.claim(value.lease_seconds)}

    @app.post('/v1/worker/{request_id}/renew', dependencies=[Depends(worker)])
    def renew(request_id: str, value: Renew):
        return queue.renew(request_id, value.lease_token, value.lease_seconds)

    @app.post('/v1/worker/{request_id}/result', dependencies=[Depends(worker)])
    def finish(request_id: str, value: Result):
        return queue.finish(request_id, value.lease_token, value.state, value.result)

    return app


def from_environment():
    def credential(name):
        return Path(os.environ[name]).read_text(encoding='utf-8').strip()
    grocery_config = None
    if os.environ.get('ASSISTANT_GROCERIES_TOKEN_FILE'):
        grocery_config = {
            'path': os.environ.get('ASSISTANT_GROCERIES_DB', '/data/groceries.sqlite3'),
            'internal_token': credential('ASSISTANT_GROCERIES_TOKEN_FILE'),
            'ha_url': 'http://homeassistant:8123',
            'assets': '/app/apps/groceries',
            'store_info': json.loads(Path('/data/grocery-store.json').read_text()) if Path('/data/grocery-store.json').is_file() else {},
        }
    notification_path=Path(os.environ.get('ASSISTANT_NOTIFICATIONS_CONFIG','/data/notifications.json'))
    notifications=json.loads(notification_path.read_text()) if notification_path.is_file() else None
    if notifications and not notifications.get('enabled',False): notifications=None
    task_links=None
    if notifications:
        from .task_links import TaskLinks
        task_links=TaskLinks.load(Path(os.environ.get('ASSISTANT_QUEUE_DB','/data/queue.sqlite3')).with_name('task-links.key'))
    voice_path=Path(os.environ.get('ASSISTANT_VOICE_CONFIG','/data/voice.json'))
    voice=json.loads(voice_path.read_text()) if voice_path.is_file() else None
    return create_app(os.environ.get('ASSISTANT_QUEUE_DB', '/data/queue.sqlite3'),
                      credential('ASSISTANT_SUBMIT_TOKEN_FILE'),
                      credential('ASSISTANT_WORKER_TOKEN_FILE'), groceries=grocery_config,notifications=notifications,task_links=task_links,voice=voice,
                      release_publish_token_file=os.environ.get('ASSISTANT_RELEASE_PUBLISH_TOKEN_FILE'))
