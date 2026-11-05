"""User-scoped workout records with revision conflicts and retry-safe mutations."""
from contextlib import contextmanager
from copy import copy
import hashlib
import json
import re
from pathlib import Path
import secrets
import sqlite3
import time
from ..relay.store import Conflict, Missing
from ..relay.wakeups import Wakeups, log_phases
from .models import MODELS, Mutation, validate
from .schema import OWNER, initialize


def brief_text(text, limit=170, sentences=2):
    """Briefs stay brief whatever the model returned: a couple of sentences, never a wall of text."""
    plain=(text or '').split('Proposed changes:')[0]
    plain=re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',plain)
    plain=re.sub(r'(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)','',plain)
    plain=plain.replace('**','').replace('__','').replace('`','')
    plain=re.sub(r'(?<!\w)[*_]([^*_\n]+)[*_](?!\w)',r'\1',plain)
    words=' '.join(plain.split())
    kept=' '.join(re.split(r'(?<=[.!?])\s+',words)[:sentences])
    return kept if len(kept)<=limit else kept[:limit].rsplit(' ',1)[0].rstrip(' ,;:')+'…'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Workouts:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.user_id = OWNER
        self.competition = False
        # Shared by every for_user() copy: wake long polls after the writing transaction commits.
        self.wakeups = Wakeups()
        self._pending_wakeups = {}
        self._scrub = set()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            initialize(db)

    def for_user(self, user_id):
        scoped = copy(self)
        scoped.user_id = user_id
        return scoped

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        # Deleted photo bytes are overwritten, not left in free pages.
        db.execute('PRAGMA secure_delete=ON')
        self._pending_wakeups[id(db)] = set()
        try:
            yield db
            db.commit()
            if id(db) in self._scrub:
                # Old page images in the write-ahead log would still hold them until it is reused.
                try: db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                except sqlite3.Error: pass
        except BaseException:
            self._pending_wakeups.pop(id(db), None)
            db.rollback()
            raise
        finally:
            self._scrub.discard(id(db))
            db.close()
        keys = self._pending_wakeups.pop(id(db), None)
        if keys: self.wakeups.notify(*keys)

    def wake(self, db, *kinds, user_id=None):
        """Mark trainer work ('trainer') or a visible chat change ('conversation') for this user."""
        keys = {(kind, user_id or self.user_id) for kind in kinds}
        pending = self._pending_wakeups.get(id(db))
        if pending is None: self.wakeups.notify(*keys)  # not one of our transactions: no commit to wait for
        else: pending.update(keys)

    def mutate(self, operations, actor='owner', db=None):
        if db is None:
            with self.db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                return self.mutate(operations, actor, conn)
        results = []
        for value in operations:
            op = Mutation.model_validate(value).model_dump()
            if op['kind'] not in MODELS:
                raise ValueError('Unknown entity kind')
            request = encoded(op)
            prior = db.execute('SELECT * FROM mutations WHERE user_id=? AND id=?', (self.user_id, op['mutation_id'])).fetchone()
            if prior:
                if prior['request'] != request: raise Conflict('Mutation ID reused with different data')
                results.append(json.loads(prior['result']))
                continue
            old = db.execute('SELECT * FROM entities WHERE user_id=? AND kind=? AND id=?', (self.user_id, op['kind'], op['id'])).fetchone()
            if (old['revision'] if old else 0) != op['base_revision']:
                raise Conflict('Stale workout revision: '+op['kind']+'/'+op['id'])
            data = {} if op['deleted'] else validate(op['kind'], op['data'])
            if op['kind'] == 'sprint' and data.get('scheduled'):
                previous = json.loads(old['data']).get('scheduled', []) if old and not old['deleted'] else []
                timed = any(slot.get('starts_at') for slot in data['scheduled'])
                if (self.user_id != OWNER or timed) and data['scheduled'] != previous and not self.scheduled_sprints_enabled(db):
                    raise Conflict('Enable scheduled sprints in Iron League settings before adding or changing a schedule.')
            if op['kind'] == 'photo' and not op['deleted']: self.check_photo(db, op['id'], data)
            if len(encoded(data).encode()) > 256*1024: raise ValueError('Workout record exceeds 256 KiB')
            now = self.clock()
            revision = db.execute('INSERT INTO changes(user_id,kind,id,deleted,data,at,actor) VALUES(?,?,?,?,?,?,?)',
                (self.user_id, op['kind'], op['id'], op['deleted'], encoded(data), now, actor)).lastrowid
            db.execute('INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?,?)',
                (self.user_id, op['kind'], op['id'], revision, op['deleted'], encoded(data), now))
            result = dict(kind=op['kind'], id=op['id'], revision=revision, deleted=op['deleted'], data=data, updated=now)
            if op['kind'] == 'workout':
                if op['deleted']:
                    if db.execute("DELETE FROM trainer WHERE user_id=? AND id=? AND state='queued'",(self.user_id, 'brief_workout_'+op['id'])).rowcount:
                        self.wake(db, 'conversation')
                else:
                    self.enqueue_workout_brief(db,op['id'],data,old,revision)
                    if self.competition:
                        from .competition import record_rank_ups
                        record_rank_ups(db,self,op['id'],data,old)
            if op['kind'] == 'sprint' and not op['deleted'] and data.get('status') == 'completed': self.enqueue_sprint_brief(db,op['id'],data)
            db.execute('INSERT INTO mutations VALUES(?,?,?,?)', (self.user_id, op['mutation_id'], request, encoded(result)))
            results.append(result)
            if op['kind'] == 'photo' and old and not old['deleted']: self.release_photo(db, op['id'], json.loads(old['data']), op['deleted'])
        return results

    def has_vault_photo(self, db, identifier):
        # The encrypted vault exists only when identity is required; without it no photo can be encrypted.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='train_vault_objects'").fetchone(): return False
        return bool(db.execute("SELECT 1 FROM train_vault_objects WHERE user_id=? AND kind='photo' AND id=?",
                               (self.user_id, identifier)).fetchone())

    def check_photo(self, db, identifier, data):
        def uploaded(blob):
            return db.execute('SELECT 1 FROM blobs WHERE user_id=? AND id=?', (self.user_id, blob)).fetchone()
        if data['vault']:
            if not self.has_vault_photo(db, identifier): raise ValueError('Encrypt and store the photo first')
        elif not uploaded(data['blob_id']): raise ValueError('Upload the photo first')
        if data.get('shared_blob_id') and not uploaded(data['shared_blob_id']): raise ValueError('Upload the shared photo first')

    def release_photo(self, db, identifier, previous, deleted):
        '''Delete plaintext bytes the previous version referenced once no live photo still references them.'''
        for blob in {previous.get('blob_id'), previous.get('shared_blob_id')} - {None}:
            if not db.execute('''SELECT 1 FROM entities WHERE user_id=? AND kind='photo' AND deleted=0
                    AND (json_extract(data,'$.blob_id')=? OR json_extract(data,'$.shared_blob_id')=?)''', (self.user_id, blob, blob)).fetchone():
                db.execute('DELETE FROM blobs WHERE user_id=? AND id=?', (self.user_id, blob))
                self._scrub.add(id(db))
        if deleted and previous.get('vault') and self.has_vault_photo(db, identifier):
            db.execute("DELETE FROM train_vault_objects WHERE user_id=? AND kind='photo' AND id=?", (self.user_id, identifier))

    def end_photo_shares(self, db, identifier, photos):
        '''After a question is answered, drop the plaintext copies shared only for it.'''
        row = db.execute('SELECT photo_ids FROM train_reminder_preferences WHERE user_id=?', (self.user_id,)).fetchone()
        kept = set(json.loads(row['photo_ids'])) if row else set()
        for photo in photos:
            entity = db.execute("SELECT * FROM entities WHERE user_id=? AND kind='photo' AND id=? AND deleted=0", (self.user_id, photo)).fetchone()
            if not entity or photo in kept: continue
            data = json.loads(entity['data'])
            if not data.get('vault') or not data.get('shared_blob_id'): continue
            # Another pending question may still need the same shared copy.
            if db.execute('''SELECT 1 FROM trainer, json_each(trainer.photos) WHERE trainer.user_id=? AND trainer.id!=?
                    AND trainer.state IN ('queued','running') AND json_each.value=?''', (self.user_id, identifier, photo)).fetchone(): continue
            mutation = hashlib.sha256(('unshare:'+identifier+':'+photo+':'+str(entity['revision'])).encode()).hexdigest()
            self.mutate([dict(mutation_id=mutation, kind='photo', id=photo, base_revision=entity['revision'],
                              data={**data, 'shared_blob_id': None})], 'system', db)

    def scheduled_sprints_enabled(self, db=None):
        if db is None:
            with self.db() as conn:
                return self.scheduled_sprints_enabled(conn)
        row = db.execute('SELECT scheduled_sprints FROM train_reminder_preferences WHERE user_id=?',
                         (self.user_id,)).fetchone()
        return bool(row and row['scheduled_sprints'])

    @staticmethod
    def row(row):
        data = dict(row)
        data.pop('user_id', None)
        return {**data, 'deleted': bool(row['deleted']), 'data': json.loads(row['data'])}

    def get(self, kind, identifier):
        with self.db() as db:
            row = db.execute('SELECT * FROM entities WHERE user_id=? AND kind=? AND id=?', (self.user_id, kind, identifier)).fetchone()
            if not row: raise Missing('Workout record not found')
            return self.row(row)

    def list(self, kind=None, offset=0, limit=100):
        if not 1 <= limit <= 200 or offset < 0: raise ValueError('Invalid page')
        with self.db() as db:
            rows = db.execute('SELECT * FROM entities WHERE user_id=? AND deleted=0 AND (? IS NULL OR kind=?) ORDER BY updated DESC,id LIMIT ? OFFSET ?',
                              (self.user_id, kind, kind, limit+1, offset)).fetchall()
        return {'items': [self.row(r) for r in rows[:limit]], 'next_offset': offset+limit if len(rows)>limit else None}

    def changes(self, after=0, limit=100):
        if after < 0 or not 1 <= limit <= 200: raise ValueError('Invalid cursor')
        with self.db() as db:
            rows = db.execute('SELECT * FROM changes WHERE user_id=? AND revision>? ORDER BY revision LIMIT ?', (self.user_id, after, limit+1)).fetchall()
        items = [self.row(r) for r in rows[:limit]]
        return {'schema_version': 1, 'items': items, 'cursor': items[-1]['revision'] if items else after, 'has_more': len(rows)>limit}

    def export(self):
        with self.db() as db:
            return {'schema_version': 1, 'entities': [self.row(r) for r in db.execute('SELECT * FROM entities WHERE user_id=? ORDER BY kind,id', (self.user_id,))],
                    'imports': [json.loads(r['report']) for r in db.execute('SELECT report FROM imports WHERE user_id=? ORDER BY at', (self.user_id,))],
                    'conversation': self.conversation(db=db)}

    def original_import(self, digest):
        with self.db() as db:
            row=db.execute('SELECT original,raw FROM imports WHERE user_id=? AND hash=?',(self.user_id, digest)).fetchone()
            if not row: raise Missing('Original import not found')
            return row['original'] if row['original'] is not None else row['raw'].encode('utf-8')

    def put_blob(self, identity, mime, body):
        if len(body)>8*1024*1024 or not body: raise ValueError('Photo must be 1 byte to 8 MiB')
        if hashlib.sha256(body).hexdigest() != identity: raise ValueError('Photo checksum mismatch')
        valid = ((mime=='image/jpeg' and body.startswith(b'\xff\xd8\xff')) or
                 (mime=='image/png' and body.startswith(b'\x89PNG\r\n\x1a\n')) or
                 (mime=='image/webp' and body[:4]==b'RIFF' and body[8:12]==b'WEBP'))
        if not valid: raise ValueError('Use a JPEG, PNG or WebP original')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM blobs WHERE user_id=? AND id=?', (self.user_id, identity)).fetchone(): return {'id': identity, 'created': False}
            total = db.execute('SELECT coalesce(sum(length(body)),0) FROM blobs WHERE user_id=?', (self.user_id,)).fetchone()[0]
            if total+len(body)>512*1024*1024: raise ValueError('Workout photo storage quota reached')
            db.execute('INSERT INTO blobs VALUES(?,?,?,?,?)', (self.user_id, identity, mime, body, self.clock()))
        return {'id': identity, 'created': True}

    def blob(self, identity):
        with self.db() as db:
            row = db.execute('SELECT mime,body FROM blobs WHERE user_id=? AND id=?', (self.user_id, identity)).fetchone()
            if not row: raise Missing('Photo not found')
            return row['mime'], row['body']

    def heartbeat(self, state='ready', detail=''):
        if state not in ('ready', 'busy', 'blocked'): raise ValueError('Invalid trainer readiness')
        with self.db() as db:
            before = self.status(db)
            db.execute('INSERT OR REPLACE INTO specialist VALUES(?,1,?,?,?)', (self.user_id, self.clock(), state, detail[:500]))
            after = self.status(db)
            if (before['available'], before['state']) != (after['available'], after['state']):
                self.wake(db, 'conversation')

    def status(self, db=None):
        if db is None:
            with self.db() as conn: return self.status(conn)
        row = db.execute('SELECT * FROM specialist WHERE user_id=? AND id=1', (self.user_id,)).fetchone()
        fresh = bool(row and self.clock()-row['seen']<90)
        online = fresh and row['state'] in ('ready', 'busy')
        # A fresh 'blocked' heartbeat means no coach engine has allowance (usage limit): say so instead of "offline".
        state = row['state'] if fresh and row['state'] in ('ready', 'busy', 'blocked') else 'unavailable'
        return {'available': online, 'state': state,
                'last_seen': row['seen'] if row else None, 'transport': 'persistent_codex_session'}

    def question(self, identifier, text, photos=None, photo_approval=False, context=None):
        photos = photos or []
        if not text.strip() or len(text)>8000: raise ValueError('Question must be 1..8000 characters')
        if len(photos)>6 or len(set(photos)) != len(photos): raise ValueError('Choose at most six distinct photos')
        if photos and not photo_approval: raise ValueError('Approve analysis of these photos explicitly')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM trainer WHERE user_id=? AND id=?', (self.user_id, identifier)).fetchone()
            if old:
                if (old['question'],old['photos'],old['context']) != (text,encoded(photos),encoded(context or {})):
                    raise Conflict('Question ID already used')
                return {'id': identifier, 'state': old['state']}
            for photo in photos:
                row = db.execute("SELECT data FROM entities WHERE user_id=? AND kind='photo' AND id=? AND deleted=0", (self.user_id, photo)).fetchone()
                if not row: raise ValueError('Selected photo is missing')
                data = json.loads(row['data'])
                if not (data.get('blob_id') or data.get('shared_blob_id')):
                    raise ValueError('Share the chosen photos for this question first')
            db.execute('INSERT INTO trainer(user_id,id,question,photos,context,created,state) VALUES(?,?,?,?,?,?,?)',
                       (self.user_id, identifier, text, encoded(photos), encoded(context or {}), self.clock(), 'queued'))
            self.wake(db, 'trainer', 'conversation')
        return {'id': identifier, 'state': 'queued'}

    def conversation_view(self, limit=100, before=None):
        """The chat plus a version that changes only when something the athlete sees changes."""
        with self.db() as db:
            items, status = self.conversation(limit, before, db), self.status(db)
        signature = [(i['id'], i['state'], i['answered_at'], i['approved'],i.get('partial_revision',0)) for i in items]
        version = hashlib.sha256(encoded([signature, status['available'], status['state']]).encode()).hexdigest()[:24]
        return {'items': items, 'status': status, 'version': version}

    def conversation(self, limit=100, before=None, db=None):
        if not 1 <= limit <= 200: raise ValueError('Invalid conversation limit')
        if db is None:
            with self.db() as conn: return self.conversation(limit,before,conn)
        rows = db.execute("""SELECT * FROM trainer WHERE user_id=? AND (? IS NULL OR created<?)
            AND coalesce(json_extract(context,'$.purpose'),'')!='scheduled_reminder'
            ORDER BY created DESC,rowid DESC LIMIT ?""",
                          (self.user_id, before, before, limit)).fetchall()
        from ..relay.answer_streams import read_many
        partials=read_many(db,'coach:'+self.user_id,[r['id'] for r in rows if r['state']=='running'])
        return [{**{k: json.loads(r[k]) if k in ('photos','context','proposals') and r[k] else r[k]
                 for k in ('id','question','photos','context','created','state','answer','answered_at','proposals','approved')},
                 **partials.get(r['id'],{})} for r in reversed(rows)]

    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""DELETE FROM trainer WHERE user_id=? AND state IN ('queued','running')
                AND json_extract(context,'$.purpose')='scheduled_reminder'
                AND json_extract(context,'$.expires_at')<=?
                AND (state='queued' OR lease_until<=?)""", (self.user_id, self.clock(), self.clock()))
            if db.execute("SELECT 1 FROM trainer WHERE user_id=? AND state='running' AND lease_until>?",(self.user_id, self.clock())).fetchone(): return None
            row = db.execute("""SELECT * FROM trainer WHERE user_id=?
                AND ((state='queued' AND coalesce(json_extract(context,'$.not_before'),0)<=?)
                     OR (state='running' AND lease_until<=?))
                ORDER BY CASE WHEN json_extract(context,'$.purpose')='scheduled_reminder' THEN 0 ELSE 1 END,
                         created,rowid LIMIT 1""", (self.user_id, self.clock(), self.clock())).fetchone()
            if not row: return None
            token = secrets.token_urlsafe(24)
            context = json.loads(row['context'])
            if context.get('shortfalls'):
                prefs = db.execute('SELECT roast FROM train_reminder_preferences WHERE user_id=?', (self.user_id,)).fetchone()
                if not prefs or not prefs['roast']:
                    context.pop('shortfalls')
            timings = json.loads(row['timings'] or '{}')
            timings.update(claimed=self.clock(), claims=timings.get('claims', 0)+1)
            timings.setdefault('first_claimed', timings['claimed'])
            db.execute("UPDATE trainer SET state='running',token=?,lease_until=?,timings=? WHERE user_id=? AND id=?",
                       (token, self.clock()+120, encoded(timings), self.user_id, row['id']))
            self.wake(db, 'conversation')
            return dict(id=row['id'],question=row['question'],photos=json.loads(row['photos']),context=context,token=token)

    def renew(self, identifier, token):
        with self.db() as db:
            count = db.execute("UPDATE trainer SET lease_until=? WHERE user_id=? AND id=? AND token=? AND state='running' AND lease_until>?",
                               (self.clock()+120, self.user_id, identifier, token, self.clock())).rowcount
            if not count: raise Conflict('Trainer lease lost')

    def finish(self, identifier, token, answer, proposals, state='completed',assessment=None,timings=None):
        if state not in ('completed','failed'): raise ValueError('Invalid outcome')
        if not isinstance(answer,str) or not 1<=len(answer)<=24000 or len(proposals)>20: raise ValueError('Invalid specialist response')
        validated = [Mutation.model_validate(p).model_dump() for p in proposals]
        # Owner-approved revisions retain original imports and the entity history.
        for p in validated:
            if p['kind'] not in ('exercise','template','sprint','workout'): raise ValueError('Unknown trainer proposal kind')
            if not p['deleted']: validate(p['kind'],p['data'])
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM trainer WHERE user_id=? AND id=?',(self.user_id, identifier)).fetchone()
            if (prior and prior['state']==state and prior['token']==token
                    and prior['answer']==answer and prior['proposals']==encoded(validated)):
                return
            job = db.execute("SELECT * FROM trainer WHERE user_id=? AND id=? AND token=? AND state='running' AND lease_until>?",(self.user_id, identifier, token, self.clock())).fetchone()
            if not job: raise Conflict('Trainer lease lost')
            context=json.loads(job['context'])
            if context.get('purpose') == 'scheduled_reminder' and (validated or assessment):
                raise ValueError('Reminder jobs can only write notification text')
            if state=='failed' and (context.get('workout_id') or context.get('purpose')=='sprint_brief') and context.get('attempts',0)<12:
                # A limit or outage shouldn't lose the brief: try again later, about six hours in all.
                context.update(attempts=context.get('attempts',0)+1,not_before=self.clock()+1800)
                db.execute("UPDATE trainer SET state='queued',token=NULL,lease_until=NULL,context=? WHERE user_id=? AND id=?",(encoded(context), self.user_id, identifier))
                self.wake(db, 'conversation')
                return
            self.check_proposals(db,validated)
            if assessment:
                if state!='completed': raise ValueError('Failed jobs cannot save estimates')
                allowed = json.loads(job['photos'])
                data = validate('composition',assessment)
                if data['source_question']!=identifier or not set(data['photo_ids'])<=set(allowed):
                    raise ValueError('Photo analysis was not approved for these images')
                for photo in data['photo_ids']:
                    if not db.execute("SELECT 1 FROM entities WHERE user_id=? AND kind='photo' AND id=? AND deleted=0",(self.user_id, photo)).fetchone():
                        raise ValueError('An approved photo was deleted during analysis')
                self.mutate([dict(mutation_id=hashlib.sha256(('assessment:'+identifier).encode()).hexdigest(),kind='composition',id=identifier,base_revision=0,data=data)],'approved_photo_analysis',db)
            phases = self.phases(job, timings)
            changed = db.execute("UPDATE trainer SET answer=?,proposals=?,state=?,answered_at=?,lease_until=NULL,timings=? WHERE user_id=? AND id=? AND token=? AND state='running' AND lease_until>?",
                (answer, encoded(validated), state, self.clock(), encoded(phases), self.user_id, identifier, token, self.clock())).rowcount
            if not changed: raise Conflict('Trainer lease lost')
            self.end_photo_shares(db, identifier, json.loads(job['photos']))
            self.wake(db, 'conversation')
        log_phases('trainer', f"purpose={context.get('purpose') or 'question'} state={state} claims={phases.get('claims', 1)}", [
            ('queued_to_claimed', phases.get('first_claimed', phases.get('claimed', job['created'])) - job['created']),
            ('claimed_to_model', phases['model_started'] - phases['claimed'] if 'model_started' in phases else None),
            ('model_to_first_output', phases['first_output'] - phases['model_started'] if {'first_output', 'model_started'} <= phases.keys() else None),
            ('model_to_first_text', phases['first_text'] - phases['model_started'] if {'first_text', 'model_started'} <= phases.keys() else None),
            ('model', phases['model_finished'] - phases['model_started'] if {'model_finished', 'model_started'} <= phases.keys() else None),
            ('claimed_to_answered', phases['answered'] - phases['claimed'] if 'claimed' in phases else None),
            ('total', phases['answered'] - job['created'])])

    def phases(self, job, reported):
        """Relay timestamps plus the coach's offsets (seconds after it received the claim, on its own clock)."""
        phases = json.loads(job['timings'] or '{}') if 'timings' in job.keys() else {}
        claimed = phases.get('claimed')
        for name in ('model_started', 'first_output', 'first_text', 'model_finished'):
            offset = (reported or {}).get(name + '_after')
            if claimed is not None and offset is not None:
                phases[name] = claimed + offset
        phases.update(queued=job['created'], answered=self.clock())
        return phases

    def approve(self, identifier):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM trainer WHERE user_id=? AND id=?', (self.user_id, identifier)).fetchone()
            if not row or row['state']!='completed': raise Missing('Completed trainer answer not found')
            proposals = json.loads(row['proposals'] or '[]')
            if not row['approved']: self.check_proposals(db,proposals)
            result = self.mutate(proposals,'approved_trainer_proposal',db)
            db.execute('UPDATE trainer SET approved=1 WHERE user_id=? AND id=?', (self.user_id, identifier))
            self.wake(db, 'conversation')
            return {'approved': True, 'results': result}

    def check_proposals(self, db, proposals):
        for p in proposals:
            row=db.execute('SELECT * FROM entities WHERE user_id=? AND kind=? AND id=?',(self.user_id, p['kind'], p['id'])).fetchone()
            if (row['revision'] if row else 0)!=p['base_revision']:
                raise Conflict('Record changed while trainer was responding')
            if p['deleted'] and (not row or row['deleted']): raise ValueError('Cannot delete a missing workout record')
            if not p['deleted']: validate(p['kind'],p['data'])

    def next_session_brief(self):
        with self.db() as db:
            row=db.execute("SELECT * FROM trainer WHERE user_id=? AND state='completed' AND json_extract(context,'$.purpose')='next_session_brief' ORDER BY answered_at DESC,rowid DESC LIMIT 1", (self.user_id,)).fetchone()
            online=self.status(db)['available']
            pending=bool(db.execute("SELECT 1 FROM trainer WHERE user_id=? AND state IN ('queued','running') AND json_extract(context,'$.purpose')='next_session_brief'", (self.user_id,)).fetchone())
            writing=online and pending
            failed=db.execute("SELECT 1 FROM trainer WHERE user_id=? AND state='failed' AND json_extract(context,'$.purpose')='next_session_brief' AND answered_at>?",(self.user_id, row['answered_at'] or row['created'] if row else 0)).fetchone()
            if not row:
                return {'text':None,'generated_at':None,'session_id':None,'specialist_available':online,
                        'status':'writing' if writing else 'waiting' if pending else 'failed' if failed and online else 'missing' if online else 'unavailable'}
            context=json.loads(row['context']);at=row['answered_at'] or row['created']
            cursor=db.execute('SELECT coalesce(max(revision),0) FROM changes WHERE user_id=?', (self.user_id,)).fetchone()[0]
            stale=self.clock()-at>86400 or context.get('revision')!=cursor
            return {'text':brief_text(row['answer']),'generated_at':at,'session_id':context.get('session_id'),'specialist_available':online,
                    'status':'writing' if writing else 'waiting' if pending else 'failed' if stale and failed and online else 'stale' if stale else 'cached'}

    def enqueue_workout_brief(self, db, identifier, data, old, revision):
        """Queued with the workout itself, so it survives a closed app, a dead connection and an offline coach."""
        if data.get('status')!='completed' or 'companion' not in data.get('source',{}): return
        if old and not old['deleted'] and json.loads(old['data']).get('status')=='completed': return
        profile=db.execute("SELECT data FROM entities WHERE user_id=? AND kind='athlete' AND deleted=0 ORDER BY updated DESC LIMIT 1", (self.user_id,)).fetchone()
        roast = db.execute('SELECT roast FROM train_reminder_preferences WHERE user_id=?', (self.user_id,)).fetchone()
        deficits = []
        if roast and roast['roast'] and data.get('template_id'):
            template = db.execute("SELECT data FROM entities WHERE user_id=? AND kind='template' AND id=? AND deleted=0",
                                  (self.user_id, data['template_id'])).fetchone()
            if template:
                from .scheduled import shortfalls
                deficits = shortfalls(json.loads(template['data']), data)
        if not deficits and (not profile or not json.loads(profile['data']).get('auto_coach_briefs')): return
        from .wins import describe,session_wins
        rows=[self.row(r) for r in db.execute("SELECT * FROM entities WHERE user_id=? AND kind IN ('athlete','exercise','measurement','workout') AND deleted=0", (self.user_id,))]
        wins=[describe(w) for w in session_wins(rows,target=identifier)]
        question=('The owner just finished '+data['name']+'. Write a brief for them: at most two short sentences and 30 words, '
                  'how it went, then the one thing to do next session. No headings, lists or preamble. Do not change the plan or analyse photos.'
                  +(' Open by acknowledging what they achieved: '+'; '.join(wins[:3])+'.' if wins else ''))
        db.execute('INSERT OR IGNORE INTO trainer(user_id,id,question,photos,context,created,state) VALUES(?,?,?,?,?,?,?)',
            (self.user_id, 'brief_workout_'+identifier, question, '[]', encoded({'purpose':'next_session_brief','automatic':True,'workout_id':identifier,
             'session_id':'workout:'+identifier,'revision':revision,'shortfalls':deficits}), self.clock(), 'queued'))
        self.wake(db, 'trainer', 'conversation')

    def enqueue_sprint_brief(self, db, identifier, data):
        """A finished sprint gets one short review of its own, written when the coach is next free."""
        profile=db.execute("SELECT data FROM entities WHERE user_id=? AND kind='athlete' AND deleted=0 ORDER BY updated DESC LIMIT 1", (self.user_id,)).fetchone()
        if not profile or not json.loads(profile['data']).get('auto_coach_briefs'): return
        question=(f"The sprint {data['name']} ({data['start']} to {data['end']}) has ended. Write its brief: at most three short sentences and 45 words: "
                  'what improved, what held back, and the focus for the next sprint. Read its workouts for evidence. No headings, lists or preamble. Do not change the plan or analyse photos.')
        db.execute('INSERT OR IGNORE INTO trainer(user_id,id,question,photos,context,created,state) VALUES(?,?,?,?,?,?,?)',
            (self.user_id, 'brief_sprint_'+identifier, question, '[]', encoded({'purpose':'sprint_brief','automatic':True,'sprint_id':identifier}), self.clock(), 'queued'))
        self.wake(db, 'trainer', 'conversation')

    def sprint_briefs(self):
        with self.db() as db:
            rows=db.execute("SELECT * FROM trainer WHERE user_id=? AND json_extract(context,'$.purpose')='sprint_brief' ORDER BY created DESC,rowid DESC", (self.user_id,)).fetchall()
            online=self.status(db)['available']
        out={}
        for row in rows:
            ready=row['state']=='completed'
            out.setdefault(json.loads(row['context'])['sprint_id'],{'text':brief_text(row['answer'],260,3) if ready else None,'generated_at':row['answered_at'] if ready else None,
                'state':'ready' if ready else 'failed' if row['state']=='failed' else 'writing' if online else 'waiting'})
        return out

    def workout_briefs(self, limit=100):
        """The brief written for each recent workout, so History can show it long after the end screen closed."""
        with self.db() as db:
            rows=db.execute("SELECT * FROM trainer WHERE user_id=? AND json_extract(context,'$.purpose')='next_session_brief' AND json_extract(context,'$.workout_id') IS NOT NULL ORDER BY created DESC,rowid DESC LIMIT ?",(self.user_id, limit)).fetchall()
            online=self.status(db)['available']
        out={}
        for row in rows:
            if json.loads(row['context'])['workout_id'] in out: continue
            ready=row['state']=='completed'
            out[json.loads(row['context'])['workout_id']]={'text':brief_text(row['answer']) if ready else None,'generated_at':row['answered_at'] if ready else None,
                'state':'ready' if ready else 'failed' if row['state']=='failed' else 'writing' if online else 'waiting'}
        return out

    def prepare_brief(self, timezone='UTC'):
        """Owner-opted-in, debounced ahead-of-session preparation. Never uses photos."""
        from datetime import datetime,date
        from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
        from .analytics import scheduled_day
        try: today=datetime.fromtimestamp(self.clock(),ZoneInfo(timezone)).date().isoformat()
        except (ValueError,ZoneInfoNotFoundError): raise ValueError('Unknown brief timezone') from None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=[self.row(r) for r in db.execute('SELECT * FROM entities WHERE user_id=? AND deleted=0', (self.user_id,))]
            profiles=[r for r in rows if r['kind']=='athlete']
            if not profiles or not max(profiles,key=lambda r:r['updated'])['data'].get('auto_coach_briefs'):
                return {'queued':False}
            from .programs import cycle_progress
            workouts=[r for r in rows if r['kind']=='workout']
            for row in rows:
                # A sprint can end by its deadline or its target without anyone marking it complete.
                if row['kind']=='sprint' and row['data']['status']=='active' and (row['data']['end']<today or
                        (row['data'].get('cycle') and cycle_progress(row,workouts,date.fromisoformat(today))['target_reached'])):
                    self.enqueue_sprint_brief(db,row['id'],row['data'])
            if db.execute("SELECT 1 FROM trainer WHERE user_id=? AND state IN ('queued','running')", (self.user_id,)).fetchone(): return {'queued':False}
            if not rows or self.clock()-max(r['updated'] for r in rows)<120: return {'queued':False}
            if db.execute("SELECT 1 FROM trainer WHERE user_id=? AND json_extract(context,'$.workout_id') IS NOT NULL AND created>?",(self.user_id, self.clock()-21600)).fetchone(): return {'queued':False}
            # Only future scheduled work; an ongoing workout is never interrupted by auto-coaching.
            if any(r['kind']=='workout' and r['data']['status'] in ('active','paused') for r in rows): return {'queued':False}
            from .programs import next_workout
            next_item=next_workout(rows,date.fromisoformat(today))
            if next_item:
                sprint_id=next_item['sprint_id'];template_id=next_item['template_id'];when=next_item.get('date') or today
                session_id=sprint_id+':'+str(next_item['sequence_number'])+':'+(template_id or '')
            else:
                choices=[]
                completed={(r['data'].get('sprint_id'),scheduled_day(r['data']).isoformat()) for r in rows
                           if r['kind']=='workout' and r['data']['status'] in ('completed','rest','skipped')}
                for row in rows:
                    if row['kind']=='sprint' and row['data']['status'] in ('planned','active'):
                        for session in row['data'].get('scheduled',[]):
                            if session['date']>=today and (row['id'],session['date']) not in completed:
                                choices.append((session['date'],row['id'],session.get('template_id')))
                if not choices: return {'queued':False}
                when,sprint_id,template_id=sorted(choices,key=lambda c:(c[0],c[1],c[2] or ''))[0]
                session_id=sprint_id+':'+when+':'+(template_id or '')
            previous=db.execute("SELECT created FROM trainer WHERE user_id=? AND json_extract(context,'$.automatic')=1 AND json_extract(context,'$.session_id')=? ORDER BY created DESC LIMIT 1",(self.user_id, session_id)).fetchone()
            if previous and self.clock()-previous['created']<21600: return {'queued':False}
            # Include exact revisions, so retries cannot duplicate an identical brief.
            signature=hashlib.sha256(encoded(sorted((r['kind'],r['id'],r['revision']) for r in rows)).encode()).hexdigest()
            identifier='brief_'+signature
            if db.execute('SELECT 1 FROM trainer WHERE user_id=? AND id=?',(self.user_id, identifier)).fetchone(): return {'queued':False}
            cursor=db.execute('SELECT coalesce(max(revision),0) FROM changes WHERE user_id=?', (self.user_id,)).fetchone()[0]
            question = ('Prepare a concise brief for the next session using the current sprint goals, recent performance and recovery. '
                        'Do not change the plan or analyse photos.')
            context = {'purpose':'next_session_brief','automatic':True,'session_id':session_id,'revision':cursor,
                       'date':when,'sprint_id':sprint_id,'template_id':template_id}
            db.execute("""INSERT INTO trainer(user_id,id,question,photos,context,created,state)
                VALUES(?,?,?,'[]',?,?,'queued')""", (self.user_id,identifier,question,encoded(context),self.clock()))
            self.wake(db, 'trainer', 'conversation')
        return {'queued':True,'id':identifier,'state':'queued'}
