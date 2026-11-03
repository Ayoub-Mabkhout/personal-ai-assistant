"""Persist verified rank-ups and deliver them to opted-in Train members."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import logging

from .analytics import day_of
from .schema import OWNER
from .store import encoded
from .wins import session_wins

LIFETIME = 86400


def record_rank_ups(db, store, identifier, workout, old):
    if workout['status'] != 'completed' or 'companion' not in workout.get('source', {}):
        return
    if old and not old['deleted'] and json.loads(old['data'])['status'] == 'completed':
        return
    age = (datetime.fromtimestamp(store.clock(), timezone.utc).date() - day_of(workout)).days
    if not -1 <= age <= 2:
        return
    member = db.execute('SELECT name FROM train_users WHERE id=? AND share_progress=1 AND name!=?',
                        (store.user_id, '')).fetchone()
    if not member:
        return
    records = [store.row(row) for row in db.execute("""SELECT * FROM entities WHERE user_id=?
        AND deleted=0 AND kind IN ('athlete','measurement','exercise','workout')""", (store.user_id,))]
    ranks = {}
    for win in session_wins(records, target=identifier):
        if win['kind'] == 'rank':
            ranks['running' if 'distance_m' in win else win['exercise_id']] = win
    for exercise_id, win in ranks.items():
        if 'distance_m' in win:
            minutes, seconds = divmod(round(win['seconds']), 60)
            effort = f"{win['distance_m']/1000:g} km in {minutes}:{seconds:02d}"
        elif win['weight_kg']:
            effort = f"{win['weight_kg']:g} kg × {win['reps']}"
        else:
            effort = f"{win['reps']} reps"
        tag = sha256(encoded([store.user_id, identifier, exercise_id, win['tier']]).encode()).hexdigest()[:32]
        body = f"{member['name']} reached {win['tier']} on {win['name']} with {effort}."
        db.execute('INSERT OR IGNORE INTO train_rank_events VALUES(?,?,?,?,?,0)',
                   (tag, store.user_id, body, store.clock(), store.clock() + LIFETIME))


class Competition:
    def __init__(self, workouts, push, mobile):
        self.workouts, self.push, self.mobile = workouts, push, mobile
        with workouts.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS train_rank_events(
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, body TEXT NOT NULL,
                    created REAL NOT NULL, expires REAL NOT NULL, native_sent INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS train_rank_delivery(
                    id TEXT NOT NULL, endpoint TEXT NOT NULL, due REAL NOT NULL,
                    sent INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(id,endpoint));
            """)
        workouts.competition = True

    def tick(self):
        now = self.workouts.clock()
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM train_rank_delivery WHERE id IN (SELECT id FROM train_rank_events WHERE expires<=?)', (now,))
            db.execute('DELETE FROM train_rank_events WHERE expires<=?', (now,))
            db.execute('''INSERT OR IGNORE INTO train_rank_delivery(id,endpoint,due)
                SELECT event.id,sub.endpoint,? FROM train_rank_events event
                JOIN train_users source ON source.id=event.source AND source.share_progress=1
                JOIN train_users viewer ON viewer.id!=event.source AND viewer.rank_alerts=1
                JOIN train_push_subscriptions sub ON sub.user_id=viewer.id''', (now,))
            web = db.execute('''SELECT event.*,sub.endpoint,sub.data FROM train_rank_delivery delivery
                JOIN train_rank_events event ON event.id=delivery.id
                JOIN train_users source ON source.id=event.source AND source.share_progress=1
                JOIN train_push_subscriptions sub ON sub.endpoint=delivery.endpoint
                JOIN train_users viewer ON viewer.id=sub.user_id AND viewer.rank_alerts=1
                WHERE delivery.sent=0 AND delivery.due<=? ORDER BY event.created LIMIT 4''', (now,)).fetchall() if self.push else []
            db.executemany('UPDATE train_rank_delivery SET due=? WHERE id=? AND endpoint=?',
                           [(now+60, row['id'], row['endpoint']) for row in web])
            native = db.execute('''SELECT event.* FROM train_rank_events event
                JOIN train_users source ON source.id=event.source AND source.share_progress=1
                JOIN train_users viewer ON viewer.id=? AND viewer.rank_alerts=1
                WHERE event.native_sent=0 AND event.source!=? ORDER BY event.created LIMIT 8''',
                (OWNER, OWNER)).fetchall() if self.mobile else []
        for row in native:
            payload = {'type':'train_rank', 'title':'Train rank-up', 'message':row['body'],
                       'tag':row['id'], 'friend_id':row['source'], 'visibility':'private'}
            if self.mobile.enqueue(payload, ttl=max(1, int(row['expires']-now)), repeat=row['id']):
                with self.workouts.db() as db:
                    db.execute('UPDATE train_rank_events SET native_sent=1 WHERE id=?', (row['id'],))
        for row in web:
            payload = {'title':'Train rank-up','body':row['body'],'tag':row['id'],
                       'url':'/train/?friend='+row['source']}
            ttl = int(row['expires']-self.workouts.clock())
            if ttl <= 0:
                continue
            try:
                status = self.push.send(json.loads(row['data']), encoded(payload).encode(), ttl)
            except (OSError, ValueError):
                logging.warning('Train rank notification failed; delivery will retry.')
                continue
            with self.workouts.db() as db:
                if status in (404, 410):
                    db.execute('DELETE FROM train_push_subscriptions WHERE endpoint=? AND data=?',
                               (row['endpoint'], row['data']))
                elif 200 <= status < 300:
                    db.execute('UPDATE train_rank_delivery SET sent=1 WHERE id=? AND endpoint=?',
                               (row['id'], row['endpoint']))
