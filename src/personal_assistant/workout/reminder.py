"""Per-athlete scheduled notifications with durable delivery and an offline fallback."""

from hashlib import sha256
import json
import logging
from threading import Event, Thread
from typing import Annotated

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, HTTPException, Query
from pydantic import Field

from ..relay.store import Conflict, Missing
from .models import Model
from .scheduled import LEAD, MISSED_AFTER, timed_slots
from .store import brief_text, encoded
from .web_push import decode, endpoint_origin

PhotoId = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')]


def fallback(name, roast, streak):
    if not roast:
        return f'{name} starts in 30 minutes.'
    if streak == 0:
        return 'Man, get your fat ass up. Gym in thirty. Why you still looking at this? Put your damn shoes on.'
    if streak == 1:
        return 'Here we go. You skipped the last one. Get your ass out the door this time, bitch.'
    if streak == 2:
        return 'Two misses. Man, fuck your pre-workout. You need some pre-leave-the-house. Get your punk ass moving.'
    return f'{streak} times? Bitch, you got gym clothes with house mileage on ’em. Shut the fuck up about Monday. Grab your bag.'


class Preferences(Model):
    enabled: bool | None = None
    roast: bool | None = None
    scheduled_sprints: bool | None = None
    photos_enabled: bool | None = None
    photo_ids: list[PhotoId] | None = Field(default=None, max_length=12)
    photo_id: PhotoId | None = None


class Keys(Model):
    auth: str = Field(min_length=22, max_length=22)
    p256dh: str = Field(min_length=87, max_length=87)


class Subscription(Model):
    endpoint: str = Field(min_length=16, max_length=2048)
    expirationTime: float | None = None
    keys: Keys


class TrainReminders:
    def __init__(self, workouts, provider):
        self.workouts, self.provider = workouts, provider
        self.stop = Event()
        self.thread = None
        with workouts.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS train_push_subscriptions(
                    endpoint TEXT PRIMARY KEY, user_id TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS train_push_subscriptions_user ON train_push_subscriptions(user_id);
                CREATE TABLE IF NOT EXISTS train_reminder_history(
                    user_id TEXT NOT NULL, id TEXT NOT NULL, starts REAL NOT NULL,
                    title TEXT NOT NULL, body TEXT NOT NULL, photo_id TEXT, roast INTEGER NOT NULL,
                    PRIMARY KEY(user_id,id));
                CREATE TABLE IF NOT EXISTS train_reminder_delivery(
                    user_id TEXT NOT NULL, id TEXT NOT NULL, endpoint TEXT NOT NULL,
                    next_attempt REAL NOT NULL, sent INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id,id,endpoint));
            """)

    @staticmethod
    def preferences(db, user_id):
        row = db.execute('''SELECT enabled,roast,scheduled_sprints,photos_enabled,photo_ids
            FROM train_reminder_preferences WHERE user_id=?''',
                         (user_id,)).fetchone()
        if not row:
            return {'enabled': False, 'roast': False, 'scheduled_sprints': False,
                    'photos_enabled': False, 'photo_ids': [], 'photo_id': None}
        photos = json.loads(row['photo_ids'])
        return {'enabled': bool(row['enabled']), 'roast': bool(row['roast']),
                'scheduled_sprints': bool(row['scheduled_sprints']), 'photos_enabled': bool(row['photos_enabled']),
                'photo_ids': photos, 'photo_id': photos[0] if photos else None}

    @staticmethod
    def photo(db, user_id, photo_id):
        if photo_id:
            row = db.execute("SELECT data FROM entities WHERE user_id=? AND kind='photo' AND id=? AND deleted=0",
                             (user_id, photo_id)).fetchone()
            if row:
                return '/train/api/photos/' + json.loads(row['data'])['blob_id']
        return None

    def settings(self, user_id, updates=None):
        with self.workouts.db() as db:
            if updates:
                db.execute('BEGIN IMMEDIATE')
            values = self.preferences(db, user_id)
            if updates:
                values.update({key: value for key, value in updates.items() if value is not None and key != 'photo_id'})
                if 'photo_id' in updates and 'photo_ids' not in updates:
                    values['photo_ids'] = [updates['photo_id']] if updates['photo_id'] else []
                if 'photo_id' in updates or updates.get('photo_ids') is not None:
                    values['photo_ids'] = list(dict.fromkeys(values['photo_ids']))
                    if any(not self.photo(db, user_id, photo) for photo in values['photo_ids']):
                        raise Missing('Choose your own Iron League photos.')
                if updates.get('photos_enabled') and not values['roast']:
                    raise Conflict('Enable Diss mode before enabling reminder photos.')
                values['photo_id'] = next(iter(values['photo_ids']), None)
                db.execute('''INSERT OR REPLACE INTO train_reminder_preferences
                    (user_id,enabled,roast,scheduled_sprints,photos_enabled,photo_ids) VALUES(?,?,?,?,?,?)''',
                    (user_id, values['enabled'], values['roast'], values['scheduled_sprints'],
                     values['photos_enabled'], encoded(values['photo_ids'])))
            return values

    def subscribe(self, user_id, subscription):
        endpoint = subscription.endpoint
        endpoint_origin(endpoint)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decode(subscription.keys.p256dh))
        if len(decode(subscription.keys.auth)) != 16:
            raise ValueError('Invalid push authentication secret')
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT user_id FROM train_push_subscriptions WHERE endpoint=?', (endpoint,)).fetchone()
            if previous and previous['user_id'] != user_id:
                raise Conflict('This device already receives another Iron League profile’s reminders.')
            count = db.execute('SELECT count(*) FROM train_push_subscriptions WHERE user_id=?', (user_id,)).fetchone()[0]
            if not previous and count >= 8:
                raise Conflict('Remove a device before adding another.')
            db.execute('INSERT OR REPLACE INTO train_push_subscriptions VALUES(?,?,?)',
                       (endpoint, user_id, encoded(subscription.model_dump())))

    def unsubscribe(self, user_id, endpoint):
        with self.workouts.db() as db:
            db.execute('DELETE FROM train_push_subscriptions WHERE user_id=? AND endpoint=?', (user_id, endpoint))

    def history(self, user_id, identifier):
        with self.workouts.db() as db:
            row = db.execute('SELECT * FROM train_reminder_history WHERE user_id=? AND id=?', (user_id, identifier)).fetchone()
            if not row:
                raise Missing('Reminder not found')
            return self.payload(db, row)

    def payload(self, db, row):
        identifier = row['id']
        preferences = self.preferences(db, row['user_id'])
        image = None
        if preferences['roast'] and preferences['photos_enabled'] and row['photo_id'] in preferences['photo_ids']:
            image = self.photo(db, row['user_id'], row['photo_id'])
        return {'id': identifier, 'title': row['title'], 'body': row['body'], 'tag': identifier,
                'url': '/train/?reminder=' + identifier, 'image': image}

    def prepare(self, store, now):
        eligible = set()
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            preferences = self.preferences(db, store.user_id)
            if not preferences['enabled'] or not preferences['scheduled_sprints']:
                return eligible
            rows = [store.row(row) for row in db.execute("""SELECT * FROM entities
                WHERE user_id=? AND deleted=0 AND kind IN ('sprint','workout','template')""", (store.user_id,))]
            workouts = [row for row in rows if row['kind']=='workout']
            names = {row['id']: row['data']['name'] for row in rows if row['kind']=='template'}
            for sprint in rows:
                if sprint['kind'] != 'sprint' or sprint['data']['status'] not in ('planned', 'active'):
                    continue
                streak = 0
                for starts, slot, state in timed_slots(sprint, workouts):
                    if starts <= now:
                        if state == 'completed':
                            streak = 0
                        elif state == 'skipped' or (state == 'pending' and now >= starts + MISSED_AFTER):
                            streak += 1
                    elif state == 'pending' and starts <= now + LEAD + 300:
                        identifier = self.prepare_slot(db, store, preferences, sprint, slot, starts, now, streak,
                                                       names.get(slot.get('template_id'), 'Your workout'))
                        if identifier:
                            eligible.add((store.user_id, identifier))
        return eligible

    def prepare_slot(self, db, store, preferences, sprint, slot, starts, now, streak, name):
        user_id = store.user_id
        identifier = sha256(encoded([sprint['id'], slot['id'], starts]).encode()).hexdigest()[:32]
        job = 'reminder_' + identifier
        if starts > now + LEAD:
            if store.status(db)['available']:
                context = {'purpose': 'scheduled_reminder', 'expires_at': starts-LEAD,
                           'workout_name': name, 'missed_streak': streak, 'roast': preferences['roast']}
                db.execute('''INSERT OR IGNORE INTO trainer(user_id,id,question,photos,context,created,state)
                    VALUES(?,?,?,'[]',?,?,'queued')''',
                    (user_id, job, 'Write the upcoming workout notification using the supplied schedule and style.',
                     encoded(context), now))
            return
        if db.execute('SELECT 1 FROM train_reminder_history WHERE user_id=? AND id=?', (user_id, identifier)).fetchone():
            self.queue_delivery(db, user_id, identifier, now)
            return identifier
        answer = db.execute("SELECT answer,context FROM trainer WHERE user_id=? AND id=? AND state='completed' AND answered_at<=?",
                            (user_id, job, starts-LEAD)).fetchone()
        generated = ''
        if answer:
            context = json.loads(answer['context'])
            if context.get('roast') == preferences['roast'] and context.get('missed_streak') == streak:
                generated = brief_text(answer['answer'], 220, 2)
        body = generated or fallback(name, preferences['roast'], streak)
        photo_id = self.next_photo(db, user_id, preferences)
        db.execute('INSERT INTO train_reminder_history VALUES(?,?,?,?,?,?,?)',
                   (user_id, identifier, starts, 'Workout in 30 minutes', body,
                    photo_id, preferences['roast']))
        self.queue_delivery(db, user_id, identifier, now)
        return identifier

    def next_photo(self, db, user_id, preferences):
        if not preferences['roast'] or not preferences['photos_enabled']:
            return None
        photos = [photo for photo in preferences['photo_ids'] if self.photo(db, user_id, photo)]
        if not photos:
            return None
        previous = db.execute('''SELECT photo_id FROM train_reminder_history WHERE user_id=? AND photo_id IS NOT NULL
            ORDER BY starts DESC,rowid DESC LIMIT 1''', (user_id,)).fetchone()
        if previous and previous['photo_id'] in photos:
            return photos[(photos.index(previous['photo_id']) + 1) % len(photos)]
        return photos[0]

    @staticmethod
    def queue_delivery(db, user_id, identifier, now):
        db.execute('''INSERT OR IGNORE INTO train_reminder_delivery(user_id,id,endpoint,next_attempt)
            SELECT user_id,?,endpoint,? FROM train_push_subscriptions WHERE user_id=?''',
            (identifier, now, user_id))

    def tick(self):
        now = self.workouts.clock()
        with self.workouts.db() as db:
            users = [row['user_id'] for row in db.execute('''SELECT user_id FROM train_reminder_preferences p
                WHERE enabled=1 AND scheduled_sprints=1
                AND EXISTS (SELECT 1 FROM train_push_subscriptions s WHERE s.user_id=p.user_id)''')]
        eligible = set()
        for user_id in users:
            eligible.update(self.prepare(self.workouts.for_user(user_id), now))
        if eligible:
            self.deliver(now, eligible)

    def deliver(self, now, eligible):
        # Lease attempts before sending. An accepted request is never retried.
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('''SELECT h.*,d.endpoint,s.data FROM train_reminder_delivery d
                JOIN train_reminder_history h USING(user_id,id)
                JOIN train_push_subscriptions s USING(user_id,endpoint)
                JOIN train_reminder_preferences p USING(user_id)
                WHERE d.sent=0 AND d.next_attempt<=? AND h.starts>? AND p.enabled=1 AND p.scheduled_sprints=1 AND p.roast=h.roast
                ORDER BY h.starts''', (now, now)).fetchall()
            rows = [row for row in rows if (row['user_id'], row['id']) in eligible][:4]
            attempts = [(row, self.payload(db, row)) for row in rows]
            db.executemany('UPDATE train_reminder_delivery SET next_attempt=? WHERE user_id=? AND id=? AND endpoint=?',
                           [(now+60, row['user_id'], row['id'], row['endpoint']) for row in rows])
        for row, payload in attempts:
            if self.stop.is_set():
                return
            ttl = int(row['starts'] - self.workouts.clock())
            if ttl <= 0:
                continue
            try:
                status = self.provider.send(json.loads(row['data']), encoded(payload).encode(), ttl)
            except (OSError, ValueError):
                logging.warning('Iron League Web Push transport failed; delivery will retry.')
                continue
            if status in (404, 410):
                self.unsubscribe(row['user_id'], row['endpoint'])
            elif 200 <= status < 300:
                with self.workouts.db() as db:
                    db.execute('UPDATE train_reminder_delivery SET sent=1 WHERE user_id=? AND id=? AND endpoint=?',
                               (row['user_id'], row['id'], row['endpoint']))

    def start(self, competition=None):
        def run():
            while not self.stop.is_set():
                try:
                    if self.provider:
                        self.tick()
                    if competition:
                        competition.tick()
                except Exception as error:
                    logging.warning('Iron League reminder check failed (%s).', type(error).__name__)
                self.stop.wait(15)
        self.stop.clear()
        self.thread = Thread(target=run, name='train-reminders', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)


def install_reminders(router, reminders, account):
    @router.get('/reminders')
    def settings(user=Depends(account)):
        return reminders.settings(user['id'])

    @router.patch('/reminders')
    def update(body: Preferences, user=Depends(account)):
        return reminders.settings(user['id'], body.model_dump(exclude_unset=True))

    @router.get('/reminders/history/{identifier}')
    def history(identifier: str, user=Depends(account)):
        return reminders.history(user['id'], identifier)

    @router.get('/push/key')
    def push_key(user=Depends(account)):
        if not reminders.provider:
            raise HTTPException(503, 'Iron League push notifications are unavailable.')
        return {'public_key': reminders.provider.public_key}

    @router.put('/push/subscriptions')
    def subscribe(body: Subscription, user=Depends(account)):
        if not reminders.provider:
            raise HTTPException(503, 'Iron League push notifications are unavailable.')
        reminders.subscribe(user['id'], body)
        return {'ok': True}

    @router.delete('/push/subscriptions')
    def unsubscribe(body: Subscription | None = None, endpoint: str | None = Query(default=None, max_length=2048), user=Depends(account)):
        address = body.endpoint if body else endpoint
        if not address:
            raise ValueError('Provide the subscription endpoint.')
        reminders.unsubscribe(user['id'], address)
        return {'ok': True}
