"""Relay API. Service credentials and standalone owner sessions."""

import os
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .delivery import build_sender, delivery_status, fcm_provider
from .store import Conflict, Missing, Queue


class BodyLimit:
    def __init__(self, app, limit=16384):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] == 'http' and path.startswith(('/train/', '/v1/train/')):
            original_send = send
            async def send(message):
                if message['type'] == 'http.response.start':
                    from starlette.datastructures import MutableHeaders
                    headers = MutableHeaders(scope=message)
                    headers['referrer-policy'] = 'no-referrer'
                    if path.startswith(('/train/api/', '/v1/train/')):
                        headers['cache-control'] = 'private, no-store'
                    else:
                        # The web app revalidates on every load, so a deploy reaches phones without clearing caches.
                        headers['cache-control'] = 'no-cache'
                await original_send(message)
        if scope['type'] != 'http' or (scope.get('method')=='PUT' and (scope.get('path')=='/companion/v1/releases/artifact'
                                                                       or scope.get('path','').startswith('/v1/files/')
                                                                       or scope.get('path','').startswith('/groceries/v1/mobile/task-attachments/')
                                                                       or scope.get('path','').startswith('/v1/agent/tasks/')
                                                                       or '/workout/photos/' in path
                                                                       or path.startswith('/train/api/photos/'))
                                      or (scope.get('method')=='POST' and ('/workout/imports/' in path or path.startswith('/train/api/imports/')))):
            # Streamed uploads enforce their own declared, bounded size.
            return await self.app(scope, receive, send)
        body = bytearray()
        limit = 4*1024*1024 if path=='/groceries/v1/mobile/voice' else (5*1024*1024 if path=='/v1/calendar/reminders/snapshot' else 2*1024*1024 if path=='/v1/banking/summary' else (
            1024*1024 if path in ('/groceries/v1/recipes/import/preview','/groceries/v1/recipes/import/commit') else self.limit))
        if path.startswith('/groceries/v1/mobile/termux/'):
            limit=512*1024  # bounded scripts/results, including UTF-8/JSON escaping
        if path.endswith('/stream'):
            limit=512*1024  # bounded answer snapshots with JSON Unicode escaping
        if scope.get('method')=='PUT' and path.startswith('/train/api/vault/records/'):
            limit=24*1024*1024  # bounded ciphertext envelope for a 16 MiB private object
        if path.endswith('/workout/sync') or path == '/train/api/sync':
            limit=2*1024*1024
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


class AgentLease(Lease):
    session_lanes: bool = False


class WorkerTimings(BaseModel):
    """Seconds after the worker received its claim, measured on the worker's own clock."""
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    execution_started_after: float | None = Field(default=None, ge=0, le=86400)
    first_output_after: float | None = Field(default=None, ge=0, le=86400)
    execution_finished_after: float | None = Field(default=None, ge=0, le=86400)


class Result(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lease_token: str
    state: Literal['completed', 'failed', 'needs_input']
    result: dict
    timings: WorkerTimings | None = None


async def claim_job(job_queue, lease_seconds, wait, request, session_lanes=False, execution_host='laptop'):
    from .store import CLAIMABLE
    from .wakeups import long_poll, requested_wait
    job, waited = await long_poll(lambda: job_queue.claim(lease_seconds, session_lanes=session_lanes, execution_host=execution_host), job_queue.wakeups, CLAIMABLE,
                                  requested_wait(wait), request)
    # wait_seconds tells a client this relay supports long polling (and what it honoured).
    return {'job': job, 'wait_seconds': waited}


def timings_of(value):
    return value.timings.model_dump(exclude_none=True) if value.timings else None


def create_app(path, submit_token, worker_token, clock=None, groceries=None, notifications=None,task_links=None,voice=None,release_publish_token_file=None,mobile_settings_file=None,owner_credentials_file=None,file_drops=None,train_assets=None,train_push=None,train_require_identity=False,server_worker_token=None):
    if len(submit_token) < 32 or len(worker_token) < 32 or submit_token == worker_token:
        raise ValueError('Use distinct service tokens of at least 32 characters.')
    if server_worker_token is not None and (len(server_worker_token) < 32 or server_worker_token in (submit_token, worker_token)):
        raise ValueError('Use a separate server agent token of at least 32 characters.')
    queue = Queue(path, notifications=bool(notifications), **({'clock': clock} if clock else {}))
    agent_queue = Queue(Path(path).with_name('agent-queue.sqlite3'), serial=True, notifications=bool(notifications), server_enabled=bool(server_worker_token),
                        **({'clock':clock} if clock else {}))
    pump=None; reminder_pump=None; money_reminder_pump=None; sender=None; release_pump=None; native_pump=None; mobile_events=None; native_provider=None; mode=None; retailer_check=None
    if groceries:
        if groceries.get('retailer_check', {}).get('enabled'):
            from personal_assistant.groceries.store import Groceries
            from personal_assistant.groceries.rewe import RetailerCheck
            retailer_check=RetailerCheck(Groceries(groceries['path']), groceries['retailer_check'])
        from personal_assistant.groceries.mobile import Devices
        from .mobile_push import MobileEventStore,MobilePushPump
        mobile_events=MobileEventStore(Devices(Path(groceries['path']).with_name('phones.sqlite3'),**({'clock':clock} if clock else {})))
        native_provider=fcm_provider(notifications)
        native_pump=MobilePushPump(mobile_events,native_provider)
    if notifications:
        from .notifications import NotificationPump
        mode,sender=build_sender(notifications,mobile_events,native_provider)
        pump=NotificationPump({'command':queue,'agent':agent_queue},sender,notifications['public_url'],
            visibility=notifications.get('visibility','private'),task_links=task_links,max_age=3600 if mode=='native' else None)
        from .reminders import ReminderStore,ReminderPump
        reminder_store=ReminderStore(Path(path).with_name('reminders.sqlite3'),**({'clock':clock} if clock else {}))
        reminder_pump=ReminderPump(reminder_store,sender,visibility=notifications.get('visibility','private'))
    train_reminders = None
    train_competition = None
    @asynccontextmanager
    async def lifespan(app):
        if pump: pump.start()
        if reminder_pump: reminder_pump.start()
        if money_reminder_pump: money_reminder_pump.start()
        if release_pump: release_pump.start()
        if native_pump: native_pump.start()
        if retailer_check: retailer_check.start()
        if train_reminders and (train_push or mobile_events): train_reminders.start(train_competition)
        try: yield
        finally:
            if pump: pump.close()
            if reminder_pump: reminder_pump.close()
            if money_reminder_pump: money_reminder_pump.close()
            if release_pump: release_pump.close()
            if native_pump: native_pump.close()
            if retailer_check: retailer_check.close()
            if train_reminders and (train_push or mobile_events): train_reminders.close()
    app = FastAPI(title='Personal assistant relay', docs_url=None, redoc_url=None, openapi_url=None,lifespan=lifespan)
    app.state.notification_pump=pump
    app.state.reminder_pump=reminder_pump
    app.state.native_push_pump=native_pump
    app.state.mobile_events=mobile_events
    app.add_middleware(BodyLimit)
    from .owner_auth import OwnerAuth
    owner_auth=OwnerAuth(Path(path).with_name('owner-sessions.sqlite3'),owner_credentials_file or Path(path).with_name('owner-login.json'),submit_token)
    app.state.owner_auth=owner_auth
    app.include_router(owner_auth.router())
    from fastapi.responses import RedirectResponse
    @app.get('/')
    def landing(): return RedirectResponse('/groceries/')
    if groceries:
        from personal_assistant.groceries.api import router
        groceries_api=router(**groceries,owner_auth=owner_auth,phone_sender=sender, mobile_settings_file=mobile_settings_file,shopping_config=voice)
        app.state.shopping_ai=groceries_api.shopping_ai
        app.include_router(groceries_api)
        release_pump=groceries_api.release_pump
        app.state.release_pump=release_pump
        app.state.release_feed=groceries_api.release_feed
        if release_publish_token_file:
            from .release_upload import release_upload_router
            app.include_router(release_upload_router(groceries_api.release_feed,release_publish_token_file))
        if voice is not None:
            from .voice import VoiceService,voice_router
            from personal_assistant.groceries.store import Groceries
            voice_service=VoiceService(Path(path).with_name('voice.sqlite3'),groceries_api.devices,
                Groceries(groceries['path']),agent_queue,queue,config=voice,shopping=groceries_api.shopping_ai)
            app.state.voice=voice_service
            app.include_router(voice_router(voice_service))
        from .tasks import task_router
        app.include_router(task_router({'command':queue,'agent':agent_queue},
            Path(groceries['assets']).parent/'tasks',task_links=task_links,owner_auth=owner_auth,
            mobile_settings_file=mobile_settings_file or Path(groceries['path']).with_name('companion-preferences.json')))
        from .mobile_tasks import mobile_task_router
        from .mobile_push import mobile_push_router
        from .mobile_settings import mobile_settings_router
        from .task_attachments import TaskAttachments
        task_attachments=TaskAttachments(Path(path).with_name('task-attachments.sqlite3'),Path(path).with_name('task-attachments'))
        app.state.task_attachments=task_attachments
        app.include_router(mobile_task_router(groceries_api.devices,{'command':queue,'agent':agent_queue},task_attachments))
        app.include_router(mobile_push_router(mobile_events))
        app.include_router(mobile_settings_router(groceries_api.devices,
            mobile_settings_file or Path(groceries['path']).with_name('companion-preferences.json')))

    def authorization(expected):
        def verify(authorization: str | None = Header(default=None)):
            if not authorization or not secrets.compare_digest(authorization.encode(), ('Bearer ' + expected).encode()):
                raise HTTPException(401, 'Authentication required.', headers={'WWW-Authenticate': 'Bearer'})
        return verify
    submit = authorization(submit_token)
    worker = authorization(worker_token)
    def agent_worker(authorization_header: str | None = Header(default=None, alias='Authorization')):
        if (server_worker_token and authorization_header
                and secrets.compare_digest(authorization_header.encode(), ('Bearer ' + server_worker_token).encode())):
            return 'server'
        worker(authorization_header)
        return 'laptop'

    from .answer_streams import router as answer_stream_router
    app.include_router(answer_stream_router(agent_queue,agent_worker))
    from .replies import reply_router
    app.include_router(reply_router({'command':queue,'agent':agent_queue},submit))
    from .features import Features,device_auth,features_router
    features=Features(Path(path).with_name('features.sqlite3'),**({'clock':clock} if clock else {}))
    app.state.features=features
    app.include_router(features_router(features,submit,'/v1/features'))
    if groceries:
        from .task_attachments import attachment_router
        app.include_router(attachment_router(task_attachments,device_auth(groceries_api.devices),(submit_token,worker_token),agent_queue,server_worker_token))
        app.include_router(features_router(features,device_auth(groceries_api.devices),'/groceries/v1/mobile/features'))
        from .file_drops import FileDrops,file_drop_router
        drops=FileDrops(mobile_events,Path(path).with_name('file-drops'),**(file_drops or {}))
        app.state.file_drops=drops
        for drop_router in file_drop_router(drops,(submit_token,worker_token),device_auth(groceries_api.devices)):
            app.include_router(drop_router)
    task_attachments = getattr(app.state, 'task_attachments', None)
    from .banking import Banking,ConsentReminderPump,banking_router
    banking=Banking(Path(path).with_name('banking.sqlite3'),**({'clock':clock} if clock else {}))
    app.state.banking=banking
    if sender:
        money_reminder_pump=ConsentReminderPump(banking,sender,visibility=notifications.get('visibility','private'))
    app.state.money_reminder_pump=money_reminder_pump
    banking_owner,banking_public,banking_phone,banking_conversation,banking_owner_view=banking_router(
        banking,submit,device_auth(groceries_api.devices) if groceries else submit,owner_auth,task_attachments)
    app.include_router(banking_owner);app.include_router(banking_public);app.include_router(banking_conversation);app.include_router(banking_owner_view)
    if groceries: app.include_router(banking_phone)
    from personal_assistant.workout.store import Workouts
    from personal_assistant.workout.api import routers as workout_routers
    workouts=Workouts(Path(path).with_name('workout.sqlite3'),**({'clock':clock} if clock else {}))
    app.state.workouts=workouts
    for routes in workout_routers(workouts,submit,device_auth(groceries_api.devices) if groceries else None,task_attachments):
        app.include_router(routes)
    if train_assets is not None:
        from personal_assistant.workout.web import mount_train
        train_reminders, train_competition = mount_train(
            app, workouts, submit, train_assets, train_push,
            device_auth(groceries_api.devices) if groceries else None, mobile_events,require_identity=train_require_identity)
        app.state.train_reminders = train_reminders
        app.state.train_competition = train_competition
    if reminder_pump:
        from .reminders import reminder_router
        app.include_router(reminder_router(reminder_store,submit,worker))
    from .calendar_feed import CalendarFeed,calendar_router
    calendar_feed=CalendarFeed(Path(path).with_name('calendar-feed.sqlite3'),reminder_store if reminder_pump else None,**({'clock':clock} if clock else {}))
    app.state.calendar_feed=calendar_feed
    for calendar_routes in calendar_router(calendar_feed,worker,device_auth(groceries_api.devices) if groceries else None):
        app.include_router(calendar_routes)

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

    @app.get('/v1/notifications/status', dependencies=[Depends(submit)])
    def notification_status():
        return delivery_status(mode,native_provider,mobile_events)

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

    @app.post('/v1/agent/worker/heartbeat')
    def agent_heartbeat(value:Heartbeat, execution_host=Depends(agent_worker)):
        return agent_queue.heartbeat(value.readiness, execution_host)

    @app.post('/v1/agent/worker/claim')
    async def agent_claim(value:AgentLease, request:Request, wait:float=Query(default=0, ge=0), execution_host=Depends(agent_worker)):
        result=await claim_job(agent_queue, value.lease_seconds, wait, request, value.session_lanes, execution_host)
        return {**result,'session_lanes':value.session_lanes}

    @app.post('/v1/agent/worker/{request_id}/renew', dependencies=[Depends(agent_worker)])
    def agent_renew(request_id:str,value:Renew):
        return agent_queue.renew(request_id,value.lease_token,value.lease_seconds)

    @app.post('/v1/agent/worker/{request_id}/result', dependencies=[Depends(agent_worker)])
    def agent_result(request_id:str,value:Result):
        return agent_queue.finish(request_id,value.lease_token,value.state,value.result,timings_of(value))

    @app.post('/v1/worker/heartbeat', dependencies=[Depends(worker)])
    def heartbeat(value: Heartbeat):
        return queue.heartbeat(value.readiness)

    @app.post('/v1/worker/claim', dependencies=[Depends(worker)])
    async def claim(value: Lease, request: Request, wait: float = Query(default=0, ge=0)):
        return await claim_job(queue, value.lease_seconds, wait, request)

    @app.post('/v1/worker/{request_id}/renew', dependencies=[Depends(worker)])
    def renew(request_id: str, value: Renew):
        return queue.renew(request_id, value.lease_token, value.lease_seconds)

    @app.post('/v1/worker/{request_id}/result', dependencies=[Depends(worker)])
    def finish(request_id: str, value: Result):
        return queue.finish(request_id, value.lease_token, value.state, value.result, timings_of(value))

    return app


def from_environment():
    from .file_drops import settings_from_environment as file_drop_settings
    def credential(name):
        return Path(os.environ[name]).read_text(encoding='utf-8').strip()
    grocery_config = None
    if os.environ.get('ASSISTANT_GROCERIES_TOKEN_FILE'):
        grocery_config = {
            'path': os.environ.get('ASSISTANT_GROCERIES_DB', '/data/groceries.sqlite3'),
            'internal_token': credential('ASSISTANT_GROCERIES_TOKEN_FILE'),
            'assets': '/app/apps/groceries',
            'store_info': json.loads(Path('/data/grocery-store.json').read_text()) if Path('/data/grocery-store.json').is_file() else {},
            'retailer_check': json.loads(Path('/data/rewe-check.json').read_text()) if Path('/data/rewe-check.json').is_file() else {},
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
    train_push = None
    train_key = Path(os.environ.get('ASSISTANT_TRAIN_PUSH_KEY', '/data/train-web-push.pem'))
    if train_key.is_file():
        from personal_assistant.workout.web_push import WebPush
        subject_file = train_key.with_name('train-web-push-subject.txt')
        train_push = WebPush(train_key, subject_file.read_text(encoding='utf-8').strip())
    server_worker_file = Path(os.environ.get('ASSISTANT_AGENT_SERVER_TOKEN_FILE', '/data/agent-server-worker.token'))
    return create_app(os.environ.get('ASSISTANT_QUEUE_DB', '/data/queue.sqlite3'),
                      credential('ASSISTANT_SUBMIT_TOKEN_FILE'),
                      credential('ASSISTANT_WORKER_TOKEN_FILE'), groceries=grocery_config,notifications=notifications,task_links=task_links,voice=voice,
                      server_worker_token=server_worker_file.read_text(encoding='utf-8').strip() if server_worker_file.is_file() else None,
                      release_publish_token_file=os.environ.get('ASSISTANT_RELEASE_PUBLISH_TOKEN_FILE'),
                      mobile_settings_file=os.environ.get('ASSISTANT_MOBILE_SETTINGS_CONFIG'),
                      owner_credentials_file=os.environ.get('ASSISTANT_OWNER_CREDENTIALS_FILE','/data/owner-login.json'),
                      file_drops=file_drop_settings(), train_push=train_push,
                      # Iron League name and password sign-in: on while this marker sits next to the queue database.
                      train_require_identity=Path(os.environ.get('ASSISTANT_QUEUE_DB', '/data/queue.sqlite3')).with_name('train-require-identity').is_file(),
                      train_assets=os.environ.get('ASSISTANT_TRAIN_ASSETS') or (
                          '/app/apps/train-web' if Path('/app/apps/train-web/index.html').is_file() else None))
