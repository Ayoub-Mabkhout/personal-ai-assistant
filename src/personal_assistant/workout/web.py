"""Invite-only Train accounts and a limited projection for other athletes."""

import hashlib
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from ..relay.store import Conflict, Missing
from .analytics import overview
from .api import install, install_worker
from .imports import exercise, identity
from .models import Model
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


class Accounts:
    def __init__(self, workouts):
        self.workouts = workouts
        self.clock = workouts.clock
        with workouts.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS train_users(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, share_progress INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS train_invites(
                    hash TEXT PRIMARY KEY, user_id TEXT, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS train_sessions(
                    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
            """)

    def invite(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.workouts.db() as db:
            if user_id and user_id != OWNER and not db.execute(
                'SELECT 1 FROM train_users WHERE id=?', (user_id,)
            ).fetchone():
                raise Missing('Train profile not found')
            db.execute('DELETE FROM train_invites WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO train_invites VALUES(?,?,?)',
                       (digest(token), user_id, self.clock() + 7 * 86400))
        return {'invite': token}

    def join(self, name, invite):
        name = ' '.join(name.split())
        if not name or not all(char.isprintable() for char in name):
            raise ValueError('Enter a display name')
        session = secrets.token_urlsafe(32)
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            invite_hash = digest(invite)
            row = db.execute('SELECT * FROM train_invites WHERE hash=? AND expires>?',
                             (invite_hash, self.clock())).fetchone()
            if not row:
                raise HTTPException(403, 'This invite is invalid or has expired.')
            user_id = row['user_id'] or uuid4().hex
            created = db.execute('INSERT OR IGNORE INTO train_users(id,name) VALUES(?,?)',
                                 (user_id, name)).rowcount
            if created and user_id != OWNER:
                self.workouts.for_user(user_id).mutate([
                    {'kind': 'exercise', 'id': identity('train-exercise', label), 'base_revision': 0,
                     'mutation_id': identity('train-seed', label), 'data': exercise(label)}
                    for label in STARTER_EXERCISES
                ], actor='starter_catalog', db=db)
            db.execute('DELETE FROM train_invites WHERE hash=?', (invite_hash,))
            db.execute('DELETE FROM train_sessions WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO train_sessions VALUES(?,?,?)',
                       (digest(session), user_id, self.clock() + SESSION_SECONDS))
            return public_account(db.execute('SELECT * FROM train_users WHERE id=?', (user_id,)).fetchone()), session

    def authenticate(self, session):
        if not session or len(session) != 43:
            raise HTTPException(401, 'Join Train to continue.')
        with self.workouts.db() as db:
            row = db.execute(
                'SELECT u.* FROM train_sessions s JOIN train_users u ON u.id=s.user_id '
                'WHERE s.hash=? AND s.expires>?', (digest(session), self.clock())
            ).fetchone()
        if not row:
            raise HTTPException(401, 'Join Train to continue.')
        return public_account(row)

    def profile(self, user_id):
        with self.workouts.db() as db:
            row = db.execute('SELECT * FROM train_users WHERE id=?', (user_id,)).fetchone()
        if not row:
            raise Missing('Train profile not found')
        return public_account(row)

    def share(self, user_id, enabled):
        with self.workouts.db() as db:
            db.execute('UPDATE train_users SET share_progress=? WHERE id=?', (enabled, user_id))
        return self.profile(user_id)

    def roster(self):
        with self.workouts.db() as db:
            return [public_account(row) for row in db.execute('SELECT * FROM train_users ORDER BY id')]


class Join(Model):
    name: str = Field(min_length=1, max_length=80)
    invite: str = Field(min_length=43, max_length=43)


class Invite(Model):
    user_id: str | None = None


class Sharing(Model):
    share_progress: bool


def same_origin(request: Request):
    if request.method in ('GET', 'HEAD'):
        return
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') in ('cross-site', 'same-site'):
        raise HTTPException(403, 'Open Train directly to make changes.')
    if origin:
        parsed = urlsplit(origin)
        host = request.headers.get('host')
        secure = parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1'))
        if not secure or parsed.netloc != host:
            raise HTTPException(403, 'Open Train directly to make changes.')


def shared_profile(account, stats):
    sprint_keys = ('id', 'name', 'phase', 'status', 'start', 'end', 'completed', 'target_sessions')
    return {
        **account,
        'completed_workouts': stats['completed_workouts'],
        'sprints': [{key: sprint[key] for key in sprint_keys} for sprint in stats['sprint_history']],
        'progress': {
            'volume': [{'date': row['date'], 'value': row['total_volume_kg_reps']} for row in stats['workout_metrics'][-90:]],
            'lifts': [{'name': row['name'],
                       'e1rm_series': [{'date': p['date'], 'value': p['value']} for p in row['e1rm_series'][-90:]]}
                      for row in stats['exercise_stats'] if row['e1rm_series']],
        },
    }


def mount_train(app, workouts, owner_auth, assets, push=None):
    from .reminder import TrainReminders, install_reminders
    accounts = Accounts(workouts)
    reminders = TrainReminders(workouts, push)
    browser = APIRouter(prefix='/train/api', dependencies=[Depends(same_origin)])
    owner = APIRouter(prefix='/v1/train', dependencies=[Depends(owner_auth)])
    coach = APIRouter(prefix='/v1/train/users/{user_id}/workout', dependencies=[Depends(owner_auth)])

    def account(request: Request):
        return accounts.authenticate(request.cookies.get(COOKIE))

    def browser_store(user=Depends(account)):
        return workouts.for_user(user['id'])

    def coach_store(user_id: str):
        return workouts.for_user(accounts.profile(user_id)['id'])

    @browser.post('/join')
    def join(body: Join, request: Request, response: Response):
        if request.cookies.get(COOKIE):
            try:
                account(request)
            except HTTPException as error:
                if error.status_code != 401:
                    raise
            else:
                raise Conflict('This browser is already joined to Train.')
        user, session = accounts.join(body.name, body.invite)
        response.set_cookie(COOKIE, session, max_age=SESSION_SECONDS, httponly=True,
                            secure=True, samesite='strict', path='/train/api')
        return user

    @browser.get('/me')
    def me(user=Depends(account)):
        return user

    @browser.patch('/me')
    def share(body: Sharing, user=Depends(account)):
        return accounts.share(user['id'], body.share_progress)

    @browser.get('/standings')
    def standings(user=Depends(account)):
        items = []
        for member in accounts.roster():
            stats = overview(workouts.for_user(member['id']))
            items.append({**member, 'lifting_score': stats['aggregate_score'],
                          'running_score': stats['running']['rank'].get('score')})
        return {'items': items}

    @browser.get('/profiles/{user_id}')
    def profile(user_id: str, user=Depends(account)):
        member = accounts.profile(user_id)
        if user_id != user['id'] and not member['share_progress']:
            raise Missing('This athlete keeps their progress private.')
        return shared_profile(member, overview(workouts.for_user(user_id)))

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
    if Path(assets).is_dir():
        app.mount('/train', StaticFiles(directory=assets, html=True), name='train')
    return reminders
