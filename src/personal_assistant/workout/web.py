"""Iron League browser accounts and a limited projection for other athletes."""

import hashlib
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from ..relay.store import Conflict, Missing
from .analytics import overview
from .api import install, install_worker
from .imports import exercise, identity
from .models import Model
from .scheduled import MISSED_AFTER, timed_slots
from .schema import OWNER

COOKIE = 'train_session'
SESSION_SECONDS = 180 * 86400
STARTER_EXERCISES = (
    'Bench Press (Barbell)', 'Squat (Barbell)', 'Deadlift (Barbell)', 'Overhead Press (Barbell)',
    'Pull Up', 'Push Up', 'Bent Over Row (Barbell)', 'Lat Pulldown (Cable)',
    'Bench Press (Dumbbell)', 'Lateral Raise (Dumbbell)', 'Bicep Curl (Dumbbell)',
    'Leg Press (Machine)', 'Leg Curl (Machine)', 'Running (Treadmill)', 'Walking',
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public_account(row):
    return {'id': row['id'], 'name': row['name'], 'share_progress': bool(row['share_progress'])}


def own_account(row):
    return {**public_account(row), 'setup_complete': bool(row['setup_complete']),
            'rank_alerts': bool(row['rank_alerts']), 'share_schedule': bool(row['share_schedule'])}


class Accounts:
    def __init__(self, workouts):
        self.workouts = workouts
        self.clock = workouts.clock
        with workouts.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS train_users(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, share_progress INTEGER NOT NULL DEFAULT 0,
                    setup_complete INTEGER NOT NULL DEFAULT 1, rank_alerts INTEGER NOT NULL DEFAULT 0,
                    share_schedule INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS train_invites(
                    hash TEXT PRIMARY KEY, user_id TEXT, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS train_sessions(
                    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
            """)
            db.execute('BEGIN IMMEDIATE')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(train_users)')}
            if 'setup_complete' not in columns:
                db.execute('ALTER TABLE train_users ADD COLUMN setup_complete INTEGER NOT NULL DEFAULT 1')
            if 'rank_alerts' not in columns:
                db.execute('ALTER TABLE train_users ADD COLUMN rank_alerts INTEGER NOT NULL DEFAULT 0')
            if 'share_schedule' not in columns:
                db.execute('ALTER TABLE train_users ADD COLUMN share_schedule INTEGER NOT NULL DEFAULT 0')

    def invite(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.workouts.db() as db:
            if user_id and user_id != OWNER and not db.execute(
                'SELECT 1 FROM train_users WHERE id=?', (user_id,)
            ).fetchone():
                raise Missing('Iron League profile not found')
            db.execute('DELETE FROM train_invites WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO train_invites VALUES(?,?,?)',
                       (digest(token), user_id, self.clock() + 7 * 86400))
        return {'invite': token}

    def join(self, name, invite=None):
        name = ' '.join(name.split())
        if not name or not all(char.isprintable() for char in name):
            raise ValueError('Enter a display name')
        session = secrets.token_urlsafe(32)
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            user_id = uuid4().hex
            if invite is not None:
                invite_hash = digest(invite)
                row = db.execute('SELECT * FROM train_invites WHERE hash=? AND expires>?',
                                 (invite_hash, self.clock())).fetchone()
                if not row:
                    raise HTTPException(403, 'This profile link is invalid or has expired.')
                user_id = row['user_id'] or user_id
                db.execute('DELETE FROM train_invites WHERE hash=?', (invite_hash,))
            else:
                profiles = db.execute('SELECT id,name FROM train_users ORDER BY rowid')
                folded_name = name.casefold()
                for profile in profiles:
                    if profile['name'].casefold() != folded_name:
                        continue
                    if profile['id'] == OWNER:
                        raise HTTPException(403, 'Use your private profile link to open Companion history.')
                    user_id = profile['id']
                    break
            created = db.execute('INSERT OR IGNORE INTO train_users(id,name,setup_complete) VALUES(?,?,?)',
                                 (user_id, name, user_id == OWNER)).rowcount
            if user_id == OWNER:
                db.execute("UPDATE train_users SET name=? WHERE id=? AND name=''", (name, OWNER))
            if created and user_id != OWNER:
                self.workouts.for_user(user_id).mutate([
                    {'kind': 'exercise', 'id': identity('train-exercise', label), 'base_revision': 0,
                     'mutation_id': identity('train-seed', label), 'data': exercise(label)}
                    for label in STARTER_EXERCISES
                ], actor='starter_catalog', db=db)
            db.execute('DELETE FROM train_sessions WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO train_sessions VALUES(?,?,?)',
                       (digest(session), user_id, self.clock() + SESSION_SECONDS))
            return own_account(db.execute('SELECT * FROM train_users WHERE id=?', (user_id,)).fetchone()), session

    def authenticate(self, session):
        if not session or len(session) != 43:
            raise HTTPException(401, 'Join Iron League to continue.')
        with self.workouts.db() as db:
            row = db.execute(
                'SELECT u.* FROM train_sessions s JOIN train_users u ON u.id=s.user_id '
                'WHERE s.hash=? AND s.expires>?', (digest(session), self.clock())
            ).fetchone()
        if not row:
            raise HTTPException(401, 'Join Iron League to continue.')
        return own_account(row)

    def profile(self, user_id, *, own=False):
        with self.workouts.db() as db:
            row = db.execute('SELECT * FROM train_users WHERE id=?', (user_id,)).fetchone()
        if not row:
            raise Missing('Iron League profile not found')
        return own_account(row) if own else public_account(row)

    def update(self, user_id, body):
        with self.workouts.db() as db:
            if user_id == OWNER:
                db.execute("INSERT OR IGNORE INTO train_users(id,name) VALUES(?,'')", (OWNER,))
            db.execute('''UPDATE train_users SET share_progress=coalesce(?,share_progress),
                setup_complete=max(setup_complete,?), rank_alerts=coalesce(?,rank_alerts),
                share_schedule=coalesce(?,share_schedule) WHERE id=?''',
                       (body.share_progress, body.setup_complete, body.rank_alerts, body.share_schedule, user_id))
            return own_account(db.execute('SELECT * FROM train_users WHERE id=?', (user_id,)).fetchone())

    def roster(self):
        with self.workouts.db() as db:
            return [public_account(row) for row in db.execute("SELECT * FROM train_users WHERE name!='' ORDER BY id")]


class Join(Model):
    name: str = Field(min_length=1, max_length=80)
    invite: str | None = Field(default=None, min_length=43, max_length=43)
    switch_profile: bool = False


class Invite(Model):
    user_id: str | None = None


class AccountUpdate(Model):
    share_progress: bool | None = None
    setup_complete: bool = False
    rank_alerts: bool | None = None
    share_schedule: bool | None = None


class PasswordLogin(Model):
    name: str = Field(min_length=1,max_length=80)
    auth_secret: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class PasswordEnrollment(PasswordLogin):
    client_salt: str = Field(pattern=r'^[A-Za-z0-9_-]{22}$')


class PasswordRegistration(PasswordEnrollment):
    invite: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class PasskeyCredential(Model):
    credential_id: str = Field(pattern=r'^[A-Za-z0-9_-]{16,1024}$')
    auth_secret: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class PasskeyPasswordReset(Model):
    credential_id: str = Field(pattern=r'^[A-Za-z0-9_-]{16,1024}$')
    passkey_auth_secret: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    auth_secret: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    client_salt: str = Field(pattern=r'^[A-Za-z0-9_-]{22}$')


class VaultKeyUpdate(Model):
    base_revision: int = Field(ge=0,le=2**53-1,strict=True)
    record: dict


class VaultObjectUpdate(Model):
    base_revision: int = Field(ge=0,le=2**53-1,strict=True)
    envelope: dict


def same_origin(request: Request):
    if request.method in ('GET', 'HEAD'):
        return
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') in ('cross-site', 'same-site'):
        raise HTTPException(403, 'Open Iron League directly to make changes.')
    if origin:
        parsed = urlsplit(origin)
        host = request.headers.get('host')
        secure = parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1'))
        if not secure or parsed.netloc != host:
            raise HTTPException(403, 'Open Iron League directly to make changes.')


def private_response(response: Response):
    response.headers['Cache-Control']='private, no-store'


SPRINT_KEYS = ('id', 'name', 'phase', 'status', 'start', 'end', 'completed', 'target_sessions')
RANK_KEYS = ('status', 'tier', 'score', 'percentile', 'exercise_name', 'next_tier', 'progress')


def current_sprint(stats):
    for sprint in stats['sprint_history']:
        if sprint['status'] == 'active' and not sprint['ended']:
            return {key: sprint[key] for key in SPRINT_KEYS}
    return None


def shared_schedule(store, sprint):
    rows = [row for row in store.export()['entities'] if not row['deleted']]
    names = {row['id']:row['data']['name'] for row in rows if row['kind']=='template'}
    workouts = [row for row in rows if row['kind']=='workout']
    current = next((row for row in rows if row['kind']=='sprint' and row['id']==sprint['id']), None)
    result = []
    for starts, slot, state in timed_slots(current, workouts) if current else ():
        if state == 'pending':
            state = 'missed' if store.clock() >= starts + MISSED_AFTER else 'upcoming'
        elif state == 'paused':
            state = 'active'
        elif state == 'skipped' and starts <= store.clock():
            state = 'missed'
        elif state == 'rest':
            state = 'skipped'
        result.append({'id':slot['id'], 'name':names.get(slot.get('template_id'), 'Workout'),
                       'date':slot['date'], 'starts_at':slot['starts_at'], 'status':state})
    return result


def shared_profile(account, stats, store, share_schedule):
    sprint = current_sprint(stats)
    rank_fields = lambda rank: {key:rank[key] for key in RANK_KEYS if key in rank}
    return {
        **account,
        'completed_workouts': stats['completed_workouts'],
        'sprints': [{key: item[key] for key in SPRINT_KEYS} for item in stats['sprint_history']],
        'current_sprint': sprint,
        'schedule': shared_schedule(store, sprint) if sprint and share_schedule and store.scheduled_sprints_enabled() else [],
        'ranks': {'lifting_score':stats['aggregate_score'], 'running':rank_fields(stats['running']['rank']),
                  'lifts':[rank_fields(rank) for rank in stats['lift_ranks']]},
        'progress': {
            'volume': [{'date': row['date'], 'value': row['total_volume_kg_reps']} for row in stats['workout_metrics'][-90:]],
            'lifts': [{'name': row['name'],
                       'e1rm_series': [{'date': p['date'], 'value': p['value']} for p in row['e1rm_series'][-90:]]}
                      for row in stats['exercise_stats'] if row['e1rm_series']],
        },
    }


def mount_train(app, workouts, owner_auth, assets, push=None, device=None, mobile_events=None,require_identity=False):
    from .competition import Competition
    from .reminder import TrainReminders, install_reminders
    accounts = Accounts(workouts)
    if require_identity:
        from .identity import Identity
        from .private_vault import PrivateVault
        identities=Identity(workouts);vault=PrivateVault(workouts)
    else:identities=vault=None
    reminders = TrainReminders(workouts, push)
    competition = Competition(workouts, push, mobile_events)
    browser = APIRouter(prefix='/train/api', dependencies=[Depends(same_origin),Depends(private_response)])
    owner = APIRouter(prefix='/v1/train', dependencies=[Depends(owner_auth)])
    coach = APIRouter(prefix='/v1/train/users/{user_id}/workout', dependencies=[Depends(owner_auth)])

    def account(request: Request):
        user=accounts.authenticate(request.cookies.get(COOKIE))
        if require_identity:
            with workouts.db() as db:
                enrolled=db.execute('SELECT 1 FROM train_credentials WHERE user_id=?',(user['id'],)).fetchone()
            if not enrolled:raise HTTPException(403,'Set a password from this profile session before continuing.')
        return user

    def browser_store(user=Depends(account)):
        return workouts.for_user(user['id'])

    def coach_store(user_id: str):
        return workouts.for_user(accounts.profile(user_id)['id'])

    @browser.post('/join')
    def join(body: Join, request: Request, response: Response):
        if require_identity:raise HTTPException(403,'Use your name and password to sign in.')
        if request.cookies.get(COOKIE) and not body.switch_profile:
            try:
                account(request)
            except HTTPException as error:
                if error.status_code != 401:
                    raise
            else:
                raise Conflict('This browser is already joined to Iron League.')
        user, session = accounts.join(body.name, body.invite)
        response.set_cookie(COOKIE, session, max_age=SESSION_SECONDS, httponly=True,
                            secure=True, samesite='strict', path='/train/api')
        return user

    def identity_enabled():
        if not require_identity:raise HTTPException(404,'Password authentication is not enabled.')

    def client_id(request):
        # Do not accept a caller-provided JSON device ID or untrusted forwarded header.
        return request.client.host if request.client else 'unknown-client'

    def auth_call(function,*args,**kwargs):
        from .identity import LoginFailed,EnrollmentDenied,RateLimited,IdentityError,InviteInvalid
        try:return function(*args,**kwargs)
        except RateLimited as error:raise HTTPException(429,str(error),headers={'Retry-After':str(error.retry_after)}) from None
        except LoginFailed as error:raise HTTPException(401,str(error)) from None
        except InviteInvalid as error:raise HTTPException(403,str(error)) from None
        except EnrollmentDenied as error:raise HTTPException(409,str(error)) from None
        except IdentityError as error:raise HTTPException(422,str(error)) from None

    def issue_session(response):
        token=secrets.token_urlsafe(32)
        def issued(db,user_id):
            db.execute('DELETE FROM train_sessions WHERE expires<=?',(workouts.clock(),))
            db.execute('INSERT INTO train_sessions VALUES(?,?,?)',(digest(token),user_id,workouts.clock()+SESSION_SECONDS))
        def cookie():
            response.set_cookie(COOKIE,token,max_age=SESSION_SECONDS,httponly=True,secure=True,samesite='strict',path='/train/api')
            response.headers['Cache-Control']='private, no-store'
        return issued,cookie

    @browser.get('/auth/parameters',dependencies=[Depends(identity_enabled)])
    def password_parameters(response:Response,name:str=Query(min_length=1,max_length=80)):
        response.headers['Cache-Control']='private, no-store'
        return auth_call(identities.parameters,name)

    @browser.post('/auth/register',dependencies=[Depends(identity_enabled)])
    def password_register(body:PasswordRegistration,request:Request,response:Response):
        issued,cookie=issue_session(response)
        identifier=auth_call(identities.register,body.name,body.auth_secret,body.client_salt,client_id(request),
                             invite_hash=digest(body.invite),on_enroll=issued)
        cookie();return {**accounts.profile(identifier,own=True),**vault.status(identifier)}

    @browser.post('/auth/login',dependencies=[Depends(identity_enabled)])
    def password_login(body:PasswordLogin,request:Request,response:Response):
        issued,cookie=issue_session(response)
        identifier=auth_call(identities.login,body.name,body.auth_secret,client_id(request),on_login=issued)
        cookie();return {**accounts.profile(identifier,own=True),**vault.status(identifier)}

    @browser.post('/auth/claim',dependencies=[Depends(identity_enabled)])
    def password_claim(body:PasswordEnrollment,request:Request,response:Response):
        issued,cookie=issue_session(response)
        identifier=auth_call(identities.claim,body.name,body.auth_secret,body.client_salt,
                             request.cookies.get(COOKIE),client_id(request),on_enroll=issued)
        cookie();return {**accounts.profile(identifier,own=True),**vault.status(identifier)}

    @browser.post('/auth/logout',dependencies=[Depends(identity_enabled)])
    def password_logout(request:Request,response:Response):
        identities.revoke(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE,path='/train/api',secure=True,httponly=True,samesite='strict')
        response.headers['Cache-Control']='private, no-store'
        return {'signed_out':True}

    @browser.get('/auth/passkeys',dependencies=[Depends(identity_enabled)])
    def passkey_list(user=Depends(account)):
        return {'items':identities.passkeys(user['id'])}

    @browser.post('/auth/passkeys',dependencies=[Depends(identity_enabled)])
    def passkey_add(body:PasskeyCredential,user=Depends(account)):
        auth_call(identities.add_passkey,user['id'],body.credential_id,body.auth_secret)
        return {'items':identities.passkeys(user['id'])}

    @browser.delete('/auth/passkeys/{credential}',dependencies=[Depends(identity_enabled)])
    def passkey_remove(credential:str,user=Depends(account)):
        if not auth_call(identities.remove_passkey,user['id'],credential):raise Missing('Passkey not found')
        return {'items':identities.passkeys(user['id'])}

    @browser.post('/auth/passkey/login',dependencies=[Depends(identity_enabled)])
    def passkey_login(body:PasskeyCredential,request:Request,response:Response):
        issued,cookie=issue_session(response)
        identifier=auth_call(identities.passkey_login,body.credential_id,body.auth_secret,client_id(request),on_login=issued)
        cookie();return {**accounts.profile(identifier,own=True),**vault.status(identifier)}

    @browser.post('/auth/passkey/reset-password',dependencies=[Depends(identity_enabled)])
    def passkey_reset_password(body:PasskeyPasswordReset,request:Request,response:Response):
        issued,cookie=issue_session(response)
        identifier=auth_call(identities.reset_password,body.credential_id,body.passkey_auth_secret,body.auth_secret,
                             body.client_salt,client_id(request),on_enroll=issued)
        cookie();return {**accounts.profile(identifier,own=True),**vault.status(identifier)}

    @browser.get('/vault/key-envelope',dependencies=[Depends(identity_enabled)])
    def vault_key(user=Depends(account)):
        return vault.get_key(user['id'])

    @browser.put('/vault/key-envelope',dependencies=[Depends(identity_enabled)])
    def save_vault_key(body:VaultKeyUpdate,user=Depends(account)):
        return vault.put_key(user['id'],body.record,body.base_revision)

    @browser.get('/vault/records',dependencies=[Depends(identity_enabled)])
    def vault_listing(user=Depends(account),kind:str|None=Query(default=None,max_length=64),
                      cursor:str|None=Query(default=None,max_length=600),limit:int=Query(default=50,ge=1,le=100)):
        return vault.listing(user['id'],kind,cursor,limit)

    @browser.get('/vault/records/{kind}/{identifier}',dependencies=[Depends(identity_enabled)])
    def vault_record(kind:str,identifier:str,user=Depends(account)):
        return vault.get(user['id'],kind,identifier)

    @browser.put('/vault/records/{kind}/{identifier}',dependencies=[Depends(identity_enabled)])
    def save_vault_record(kind:str,identifier:str,body:VaultObjectUpdate,user=Depends(account)):
        return vault.put(user['id'],kind,identifier,body.envelope,body.base_revision)

    @browser.get('/me')
    def me(user=Depends(account)):
        return {**user,**vault.status(user['id'])} if require_identity else user

    @browser.patch('/me')
    def update_account(body: AccountUpdate, user=Depends(account)):
        return accounts.update(user['id'], body)

    @browser.get('/standings')
    def standings(user=Depends(account)):
        return standings_data()

    def standings_data():
        items = []
        for member in accounts.roster():
            stats = overview(workouts.for_user(member['id']))
            items.append({**member, 'lifting_score': stats['aggregate_score'],
                          'running_score': stats['running']['rank'].get('score'),
                          'current_sprint': current_sprint(stats) if member['share_progress'] else None})
        return {'items': items}

    @browser.get('/profiles/{user_id}')
    def profile(user_id: str, user=Depends(account)):
        return profile_data(user_id, user['id'])

    def profile_data(user_id, viewer):
        member = accounts.profile(user_id, own=True)
        if user_id != viewer and not member['share_progress']:
            raise Missing('This athlete keeps their progress private.')
        scoped = workouts.for_user(user_id)
        shared = {key:member[key] for key in ('id','name','share_progress')}
        return shared_profile(shared, overview(scoped), scoped, member['share_schedule'] or user_id==viewer)

    @owner.post('/invites')
    def invite(body: Invite):
        return accounts.invite(body.user_id)

    @owner.get('/users')
    def users():
        return {'items': accounts.roster()}

    install(browser, browser_store, browser=True)
    install_reminders(browser, reminders, account)
    install(coach, coach_store)
    install_worker(coach, coach_store)
    for router in (browser, owner, coach):
        app.include_router(router)
    if device:
        native = APIRouter(prefix='/groceries/v1/mobile/workout/friends', dependencies=[Depends(device)])

        @native.get('')
        def native_standings():
            return standings_data()

        @native.get('/me')
        def native_me():
            try:
                return accounts.profile(OWNER, own=True)
            except Missing:
                return {'rank_alerts':False,'share_progress':False,'share_schedule':False}

        @native.post('/me')
        def native_update(body: AccountUpdate):
            return accounts.update(OWNER, body)

        @native.get('/{user_id}')
        def native_profile(user_id: str):
            return profile_data(user_id, OWNER)

        app.include_router(native)
    if Path(assets).is_dir():
        app.mount('/train', StaticFiles(directory=assets, html=True), name='train')
    return reminders, competition
