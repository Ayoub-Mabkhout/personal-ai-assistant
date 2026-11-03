"""Serve Iron League over a throwaway relay seeded with invented athletes.

Development only: everything lives in a temporary directory, the service tokens are random,
and every name, number and note is synthetic. It prints a one-use join link for the browser.
"""

import argparse
import random
import secrets
import struct
import sys
import threading
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / 'src'))

from fastapi.testclient import TestClient  # noqa: E402

from personal_assistant.relay.api import create_app  # noqa: E402
from personal_assistant.workout.imports import identity  # noqa: E402

UTC = timezone.utc


def ex(label):
    return identity('train-exercise', label)


BENCH, SQUAT, DEAD, PRESS = (ex('Bench Press (Barbell)'), ex('Squat (Barbell)'),
                             ex('Deadlift (Barbell)'), ex('Overhead Press (Barbell)'))
PULL, PUSH, ROW, PULLDOWN = ex('Pull Up'), ex('Push Up'), ex('Bent Over Row (Barbell)'), ex('Lat Pulldown (Cable)')
RAISE, CURL, RUN = ex('Lateral Raise (Dumbbell)'), ex('Bicep Curl (Dumbbell)'), ex('Running (Treadmill)')


def sets(rng, exercise, weight, reps, count, warmups=1):
    out = [{'id': secrets.token_hex(6), 'exercise_id': exercise, 'kind': 'warmup',
            'weight_kg': round(weight * .5 / 2.5) * 2.5, 'reps': 8} for _ in range(warmups)]
    for _ in range(count):
        out.append({'id': secrets.token_hex(6), 'exercise_id': exercise, 'kind': 'working',
                    'weight_kg': weight, 'reps': max(1, reps + rng.choice((-1, 0, 0, 1))), 'rir': 2})
    return out


def history(rng, today, strength):
    """About eight months of a three-day cycle plus easy runs, with lifts creeping upward."""
    workouts, start = [], today - timedelta(days=240)
    templates = ['push', 'pull', 'legs']
    day, n = start, 0
    while day < today:
        progress = (day - start).days / 240
        kind = templates[n % 3]
        when = datetime(day.year, day.month, day.day, 18, rng.randint(0, 40), tzinfo=UTC)
        if kind == 'push':
            body = (sets(rng, BENCH, round(strength * (62 + 14 * progress) / 2.5) * 2.5, 6, 3)
                    + sets(rng, PRESS, round(strength * (38 + 8 * progress) / 2.5) * 2.5, 7, 3)
                    + sets(rng, RAISE, 10, 14, 3, 0) + sets(rng, PUSH, 0, 22, 2, 0))
        elif kind == 'pull':
            body = (sets(rng, PULL, round(8 * progress / 2.5) * 2.5, 8, 3, 0)
                    + sets(rng, ROW, round(strength * (55 + 10 * progress) / 2.5) * 2.5, 8, 3)
                    + sets(rng, CURL, 12.5, 12, 3, 0))
        else:
            body = (sets(rng, SQUAT, round(strength * (80 + 20 * progress) / 2.5) * 2.5, 5, 3, 2)
                    + sets(rng, DEAD, round(strength * (100 + 22 * progress) / 2.5) * 2.5, 4, 2, 2))
        sprint = 'sprint-autumn' if day >= today - timedelta(days=50) else (
            'sprint-summer' if today - timedelta(days=170) <= day < today - timedelta(days=60) else None)
        workouts.append(('w-%03d' % n, {'name': kind.title(), 'started_at': when.isoformat(), 'timezone': 'UTC',
                                         'duration_seconds': rng.randint(3000, 4600), 'status': 'completed',
                                         'sprint_id': sprint, 'template_id': ('t-' + kind) if sprint else None,
                                         'sets': body}))
        if n % 4 == 1:
            run_day = day + timedelta(days=1)
            meters = rng.choice((3000, 5000, 5000, 6000))
            pace = 330 - 25 * progress + rng.randint(-8, 8)
            workouts.append(('r-%03d' % n, {'name': 'Easy run', 'status': 'completed', 'timezone': 'UTC',
                                             'started_at': datetime(run_day.year, run_day.month, run_day.day, 7,
                                                                    tzinfo=UTC).isoformat(),
                                             'duration_seconds': int(meters / 1000 * pace),
                                             'sets': [{'id': secrets.token_hex(6), 'exercise_id': RUN,
                                                       'kind': 'working', 'distance_m': meters,
                                                       'seconds': int(meters / 1000 * pace)}]}))
        day += timedelta(days=rng.choice((1, 2, 2, 2, 3)))
        n += 1
    return workouts


def plan(today):
    def rx(exercise, sets=3, low=5, high=8, **extra):
        return {'exercise_id': exercise, 'sets': sets, 'min_reps': low, 'max_reps': high, 'rir': 2, **extra}
    templates = {
        't-push': {'name': 'Push', 'exercises': [rx(BENCH, set_plan=[{'kind': 'warmup', 'reps': 8, 'weight_kg': 40},
                                                                     {'kind': 'working', 'reps': 6, 'weight_kg': 75},
                                                                     {'kind': 'working', 'reps': 6, 'weight_kg': 75},
                                                                     {'kind': 'working', 'reps': 6, 'weight_kg': 75}]),
                                                 rx(PRESS, low=6, high=10), rx(RAISE, low=12, high=15, superset='a'),
                                                 rx(PUSH, 2, 15, 25, superset='a')]},
        't-pull': {'name': 'Pull', 'exercises': [rx(PULL, low=6, high=10), rx(ROW), rx(CURL, low=10, high=14)]},
        't-legs': {'name': 'Legs', 'exercises': [rx(SQUAT, low=4, high=6), rx(DEAD, 2, 3, 5)]},
    }
    sprints = {
        'sprint-summer': {'name': 'Summer base', 'phase': 'Build', 'status': 'completed',
                          'start': str(today - timedelta(days=170)), 'end': str(today - timedelta(days=60)),
                          'cycle': list(templates), 'target_sessions': 45,
                          'goals': ['Bench 80 kg for a single', 'Run 5 km under 27 minutes'],
                          'retrospective': 'Strength rose steadily; running improved after week six.'},
        'sprint-autumn': {'name': 'Autumn strength', 'phase': 'Strength', 'status': 'active',
                          'start': str(today - timedelta(days=50)), 'end': str(today + timedelta(days=60)),
                          'cycle': list(templates), 'target_sessions': 48,
                          'goals': ['Squat 100 kg for five', 'Ten strict pull-ups'],
                          'scheduled': [{'id': 'slot-next', 'date': str(today + timedelta(days=1)),
                                         'starts_at': f'{today + timedelta(days=1)}T18:00:00+00:00', 'template_id': 't-push'}]},
    }
    return templates, sprints


def png(width, height, top, bottom):
    """A plain vertical gradient, so the photo grid has something to show without any real picture."""
    rows = b''.join(b'\x00' + bytes(int(top[c] + (bottom[c] - top[c]) * y / height) for _ in range(width) for c in range(3))
                    for y in range(height))
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def photos(admin, path, today):
    import hashlib
    for n, (top, bottom) in enumerate((((94, 60, 200), (40, 20, 70)), ((60, 140, 160), (20, 40, 60)), ((180, 80, 120), (50, 20, 40)))):
        body = png(60, 80, top, bottom)
        digest = hashlib.sha256(body).hexdigest()
        admin.put(path + f'/photos/{digest}', content=body, headers={'Content-Type': 'image/png'}).raise_for_status()
        at = datetime.combine(today - timedelta(days=30 * n + 2), datetime.min.time(), UTC) + timedelta(hours=8)
        admin.post(path + '/sync', json={'operations': [{'kind': 'photo', 'id': f'photo-{n}', 'base_revision': 0,
                   'mutation_id': secrets.token_hex(8), 'data': {'captured_at': at.isoformat(), 'blob_id': digest,
                                                                 'pose': 'front', 'state': 'relaxed'}}]}).raise_for_status()


def coach(admin, users, stop):
    """A stand-in coach: stays online and answers every question with a fixed, plainly synthetic line."""
    while not stop.is_set():
        for user in users:
            path = f'/v1/train/users/{user}/workout'
            try:
                admin.put(path + '/trainer/heartbeat', json={'state': 'ready'})
                job = admin.post(path + '/trainer/claim').json().get('job')
                if job:
                    time.sleep(2)
                    admin.put(path + f"/trainer/{job['id']}/answer", json={
                        'token': job['token'], 'text': 'Fixture coach: steady session. Add one rep to your last working set next time.'})
            except Exception:
                pass
        stop.wait(3)


def seed(admin, user, rng, today, strength):
    path = f'/v1/train/users/{user}/workout'
    ops = []
    templates, sprints = plan(today)
    for kind, items in (('template', templates), ('sprint', sprints)):
        ops += [(kind, key, value) for key, value in items.items()]
    ops += [('workout', key, value) for key, value in history(rng, today, strength)]
    weight = 82 * strength
    for week in range(34, -1, -1):
        weight += rng.uniform(-.5, .3)
        at = datetime.combine(today - timedelta(days=week * 7), datetime.min.time(), UTC) + timedelta(hours=7)
        ops.append(('measurement', f'bw-{week}', {'measured_at': at.isoformat(), 'kind': 'bodyweight',
                                                   'value': round(weight, 1), 'unit': 'kg'}))
    ops.append(('athlete', 'self', {'name': '', 'units': 'metric', 'sex': 'male', 'height_cm': 178, 'birth_date': '1996-05-01',
                                    'goal_weight_min_kg': 76, 'goal_weight_max_kg': 79, 'auto_coach_briefs': True}))
    for start in range(0, len(ops), 100):
        batch = [{'kind': k, 'id': i, 'base_revision': 0, 'mutation_id': secrets.token_hex(8), 'data': d}
                 for k, i, d in ops[start:start + 100]]
        response = admin.post(path + '/sync', json={'operations': batch})
        response.raise_for_status()
    photos(admin, path, today)
    # One answered coach exchange so the conversation has something in it.
    admin.put(path + '/trainer/heartbeat', json={'state': 'ready'}).raise_for_status()
    asked = admin.post(path + '/trainer/questions', json={'id': secrets.token_hex(8), 'text': 'How is my squat trending?'})
    asked.raise_for_status()
    job = admin.post(path + '/trainer/claim').json()['job']
    if job:
        admin.put(path + f"/trainer/{job['id']}/answer", json={
            'token': job['token'], 'text': 'Up about 15 kg on your working sets since spring. Keep the last set at two in reserve.'
        }).raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--assets', type=Path, default=ROOT.parent / 'iron-league' / 'web')
    args = parser.parse_args()
    if not (args.assets / 'index.html').is_file():
        parser.error('Pass --assets pointing to the web directory of the Iron League repository.')
    import uvicorn
    with TemporaryDirectory() as directory:
        submit, worker = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        app = create_app(Path(directory) / 'relay.sqlite3', submit, worker, train_assets=args.assets)
        origin = f'http://localhost:{args.port}'
        admin = TestClient(app, base_url=origin, headers={'Authorization': 'Bearer ' + submit})
        rng, today = random.Random(7), date.today()
        members = []
        for name, strength, share in (('Sam', 1.0, False), ('Robin', 1.15, True), ('Kai', .85, False)):
            invite = admin.post('/v1/train/invites', json={'user_id': None}).json()['invite']
            joiner = TestClient(app, base_url=origin, headers={'Origin': origin})
            joined = joiner.post('/train/api/join', json={'name': name, 'invite': invite})
            member = joined.json()
            session = joined.headers['set-cookie'].split(';')[0]
            joiner.patch('/train/api/reminders', json={'scheduled_sprints': True}, headers={'Cookie': session}).raise_for_status()
            seed(admin, member['id'], rng, today, strength)
            if share:
                joiner.patch('/train/api/me', json={'share_progress': True, 'share_schedule': True}, headers={'Cookie': session}).raise_for_status()
            members.append(member)
        link = admin.post('/v1/train/invites', json={'user_id': members[0]['id']}).json()['invite']
        print(f'Join as Sam: {origin}/train/?invite={link}', flush=True)
        fresh = admin.post('/v1/train/invites', json={'user_id': None}).json()['invite']
        print(f'Join as a new member: {origin}/train/?invite={fresh}', flush=True)
        stop = threading.Event()
        threading.Thread(target=coach, args=(admin, [m['id'] for m in members], stop), daemon=True).start()
        try:
            uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
        finally:
            stop.set()


if __name__ == '__main__':
    main()
