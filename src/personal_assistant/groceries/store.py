"""Transactional grocery mutations. Retried phone requests cannot add twice."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


class Conflict(ValueError):
    pass


def split_items(text):
    text = re.sub(r'^(?:hey chat[, ]+)?add\s+', '', text.strip(), flags=re.I)
    text = re.sub(r'\s+to (?:my |the )?shopping list[.!]?$', '', text, flags=re.I)
    # Preserve common compound ingredient names when splitting speech.
    protected = {}
    for phrase in ('mac and cheese', 'salt and pepper', 'oil and vinegar'):
        key = f'COMPOUND{len(protected)}'
        if re.search(re.escape(phrase), text, re.I):
            protected[key] = phrase
            text = re.sub(re.escape(phrase), key, text, flags=re.I)
    values = [part.strip(' .') for part in re.split(r'\s*(?:,|;|\band\b|\bund\b)\s*', text, flags=re.I)]
    return [protected.get(part, part) for part in values if part]


class Groceries:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, quantity TEXT NOT NULL DEFAULT '',
                    complete INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
                    created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS recipes (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS mutations (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL,
                    received TEXT NOT NULL, client_created TEXT);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def snapshot(self):
        with self.db() as db:
            db.execute('BEGIN')
            snapshot = {'items': [dict(row) for row in db.execute('SELECT * FROM items ORDER BY complete,created')],
                    'recipes': [{**json.loads(row['body']), 'version': row['version']} for row in db.execute('SELECT * FROM recipes')],
                    'server_time': datetime.now(timezone.utc).isoformat()}
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='retailer_status'").fetchone():
                status = db.execute('SELECT body FROM retailer_status WHERE id=1').fetchone()
                if status: snapshot['retailer_check'] = json.loads(status['body'])
                evidence = {r['item_id']: r for r in db.execute('SELECT * FROM retailer_matches')}
                for item in snapshot['items']:
                    row = evidence.get(item['id'])
                    if row and not item['complete'] and row['fingerprint'] == hashlib.sha256(item['name'].encode()).hexdigest():
                        record = json.loads(row['body'])
                        if record['expires_at'] > time.time(): item['retailer'] = record
            return snapshot

    def mutate(self, body):
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM mutations WHERE id=?', (body['id'],)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise Conflict('This request ID was already used for a different change.')
                return json.loads(previous['result'])
            op = body['operation']
            ids = []
            if op in ('add', 'recipe_add'):
                ingredients = body.get('items') or []
                if op == 'recipe_add':
                    row = db.execute('SELECT body FROM recipes WHERE id=?', (body['target'],)).fetchone()
                    if not row:
                        raise ValueError('Recipe not found.')
                    ingredients = json.loads(row['body'])['ingredients']
                if not ingredients:
                    raise ValueError('Add at least one item.')
                for item in ingredients:
                    name = item['name'].strip()
                    if not name:
                        raise ValueError('An item needs a name.')
                    item_id = str(uuid.uuid4())
                    db.execute('INSERT INTO items(id,name,quantity,created,updated) VALUES(?,?,?,?,?)',
                               (item_id, name, item.get('quantity', ''), now, now))
                    ids.append(item_id)
            elif op in ('complete', 'update', 'delete'):
                row = db.execute('SELECT version FROM items WHERE id=?', (body['target'],)).fetchone()
                if not row or row['version'] != body.get('version'):
                    raise Conflict('This item changed on another device. Refresh before changing it.')
                if op == 'delete':
                    db.execute('DELETE FROM items WHERE id=?', (body['target'],))
                elif op == 'update':
                    name = body.get('name', '').strip()
                    if not name:
                        raise ValueError('An item needs a name.')
                    db.execute('UPDATE items SET name=?,complete=?,version=version+1,updated=? WHERE id=?',
                               (name, int(body.get('complete', False)), now, body['target']))
                else:
                    db.execute('UPDATE items SET complete=?,version=version+1,updated=? WHERE id=?',
                               (int(body.get('complete', True)), now, body['target']))
            elif op == 'recipe_delete':
                row = db.execute('SELECT version FROM recipes WHERE id=?', (body['target'],)).fetchone()
                if not row or row['version'] != body.get('version'):
                    raise Conflict('This recipe changed on another device. Refresh before deleting it.')
                db.execute('DELETE FROM recipes WHERE id=?', (body['target'],))
            elif op == 'recipe_save':
                recipe = body['recipe']
                row = db.execute('SELECT version FROM recipes WHERE id=?', (recipe['id'],)).fetchone()
                if row and row['version'] != body.get('version'):
                    raise Conflict('This recipe changed on another device. Refresh before editing it.')
                db.execute('INSERT INTO recipes(id,body,version) VALUES(?,?,1) ON CONFLICT(id) DO UPDATE SET body=excluded.body,version=recipes.version+1',
                           (recipe['id'], json.dumps(recipe, ensure_ascii=False)))
            else:
                raise ValueError('Unsupported change.')
            result = {'saved': True, 'added_ids': ids, 'received_at': now}
            db.execute('INSERT INTO mutations VALUES(?,?,?,?,?)',
                       (body['id'], fingerprint, json.dumps(result), now, body.get('created_at')))
            return result
