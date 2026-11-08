"""Camera workout proof and explicit league feed projections."""
import base64
import binascii
from collections import defaultdict
from hashlib import sha256
from io import BytesIO
import json

from ..relay.store import Conflict, Missing


PHOTO_LIMIT = 1024 * 1024
PHOTO_QUOTA = 512 * 1024 * 1024


class ProofRequired(Conflict):
    def __init__(self):
        super().__init__('Take a camera photo to finish this workout.')


def clean_photo(value):
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        raw = base64.b64decode(value, validate=True)
        if not raw or len(raw) > PHOTO_LIMIT:
            raise ValueError('Camera photo exceeds 1 MiB.')
        with Image.open(BytesIO(raw), formats=('JPEG',)) as image:
            if not (0 < image.width <= 4096 and 0 < image.height <= 4096):
                raise ValueError('Camera photo exceeds 4096 pixels per side.')
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1200, 1200))
            clean = BytesIO()
            image.convert('RGB').save(clean, format='JPEG', quality=82)
    except (binascii.Error, UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise ValueError('Take a valid JPEG photo with the camera.') from None
    body = clean.getvalue()
    if len(body) > PHOTO_LIMIT:
        raise ValueError('Camera photo exceeds 1 MiB.')
    return body, sha256(raw).hexdigest()


def save_proof(db, user_id, workout_id, revision, body):
    total = db.execute('SELECT coalesce(sum(length(body)),0) FROM workout_proofs WHERE user_id=?',
                       (user_id,)).fetchone()[0]
    if total + len(body) > PHOTO_QUOTA:
        raise Conflict('Workout photo storage quota reached.')
    db.execute('INSERT INTO workout_proofs(id,user_id,workout_id,body) VALUES(?,?,?,?)',
               (revision, user_id, workout_id, body))


def delete_proof(db, user_id, workout_id):
    post = db.execute('SELECT id FROM workout_proofs WHERE user_id=? AND workout_id=?',
                      (user_id, workout_id)).fetchone()
    if not post:
        return False
    db.execute('DELETE FROM workout_feed_comments WHERE post_id=?', (post['id'],))
    db.execute('DELETE FROM workout_proofs WHERE id=?', (post['id'],))
    return True


VISIBLE = '''FROM workout_proofs p JOIN train_users u ON u.id=p.user_id
    WHERE (p.user_id=? OR u.share_progress=1)'''


def visible_post(db, viewer, post_id):
    post = db.execute('SELECT p.id,p.user_id ' + VISIBLE + ' AND p.id=?', (viewer, post_id)).fetchone()
    if not post:
        raise Missing('Workout post not found.')
    return post


def feed(store, viewer, photo_prefix, before, limit):
    with store.db() as db:
        db.execute('BEGIN')
        rows = db.execute('''SELECT p.id,p.user_id,p.workout_id,u.name AS athlete_name,
            (SELECT count(*) FROM workout_feed_comments c WHERE c.post_id=p.id AND c.deleted=0) AS comment_count '''
            + VISIBLE + ' AND p.id<? ORDER BY p.id DESC LIMIT ?', (viewer, before, limit + 1)).fetchall()
        items = []
        for row in rows[:limit]:
            workout = json.loads(db.execute("""SELECT data FROM entities
                WHERE user_id=? AND kind='workout' AND id=?""", (row['user_id'], row['workout_id'])).fetchone()['data'])
            exercises = defaultdict(list)
            for logged in workout['sets']:
                if logged.get('completed', True) and logged['kind'] != 'note':
                    exercises[logged['exercise_id']].append({
                        key: logged.get(key) for key in ('kind', 'reps', 'weight_kg', 'distance_m', 'seconds')
                    })
            names = dict(db.execute("""SELECT e.id,json_extract(e.data,'$.name') FROM entities e
                JOIN json_each(?) ids ON ids.value=e.id
                WHERE e.user_id=? AND e.kind='exercise' AND e.deleted=0""",
                (json.dumps(list(exercises)), row['user_id'])))
            items.append({
                'id': row['id'], 'workout_id': row['workout_id'],
                'athlete': {'id': row['user_id'], 'name': row['athlete_name']},
                'name': workout['name'], 'started_at': workout['started_at'],
                'duration_seconds': workout['duration_seconds'],
                'exercises': [{'name': names.get(exercise, 'Exercise'), 'sets': sets}
                              for exercise, sets in exercises.items()],
                'photo_url': f"{photo_prefix}/{row['id']}/photo", 'comment_count': row['comment_count'],
            })
        return {'items': items, 'next_cursor': items[-1]['id'] if len(rows) > limit else None}


def photo(store, viewer, post_id):
    with store.db() as db:
        row = db.execute('SELECT p.body ' + VISIBLE + ' AND p.id=?', (viewer, post_id)).fetchone()
        if not row:
            raise Missing('Workout post not found.')
        return row['body']


COMMENT_SELECT = '''SELECT c.*,coalesce(nullif(u.name,''),'Athlete') AS author_name
    FROM workout_feed_comments c LEFT JOIN train_users u ON u.id=c.author_id'''


def public_comment(row):
    return {'id': row['id'], 'author': {'id': row['author_id'], 'name': row['author_name']},
            'text': row['text'], 'created_at': row['created_at']}


def comments(store, viewer, post_id, after, limit):
    with store.db() as db:
        db.execute('BEGIN')
        visible_post(db, viewer, post_id)
        rows = db.execute(COMMENT_SELECT + ' WHERE c.post_id=? AND c.deleted=0 AND c.id>? ORDER BY c.id LIMIT ?',
                          (post_id, after, limit + 1)).fetchall()
        return {'items': [public_comment(row) for row in rows[:limit]],
                'next_cursor': rows[limit - 1]['id'] if len(rows) > limit else None}


def add_comment(store, viewer, post_id, text, client_id):
    text = text.strip()
    if not text or any(not char.isprintable() and char != '\n' for char in text):
        raise ValueError('Enter a plain-text comment.')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        visible_post(db, viewer, post_id)
        row = db.execute(COMMENT_SELECT + ' WHERE c.post_id=? AND c.author_id=? AND c.client_id=?',
                         (post_id, viewer, client_id)).fetchone()
        if row:
            if row['deleted'] or row['text'] != text:
                raise Conflict('This comment request ID has already been used.')
            return public_comment(row)
        identifier = db.execute('''INSERT INTO workout_feed_comments
            (post_id,author_id,client_id,text,created_at) VALUES(?,?,?,?,?)''',
            (post_id, viewer, client_id, text, store.clock())).lastrowid
        return public_comment(db.execute(COMMENT_SELECT + ' WHERE c.id=?', (identifier,)).fetchone())


def delete_comment(store, viewer, post_id, comment_id):
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        post = visible_post(db, viewer, post_id)
        row = db.execute('SELECT author_id FROM workout_feed_comments WHERE id=? AND post_id=?',
                         (comment_id, post_id)).fetchone()
        if not row or viewer not in (post['user_id'], row['author_id']):
            raise Missing('Comment not found.')
        # Keep a blank tombstone so a delayed retry cannot resurrect deleted text.
        db.execute("UPDATE workout_feed_comments SET deleted=1,text='' WHERE id=?", (comment_id,))
