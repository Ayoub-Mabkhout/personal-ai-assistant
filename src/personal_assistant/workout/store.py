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
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally: db.close()

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
                    raise Conflict('Enable scheduled sprints in Train settings before adding or changing a schedule.')
            if op['kind'] == 'photo' and not op['deleted']:
                if not db.execute('SELECT 1 FROM blobs WHERE user_id=? AND id=?', (self.user_id, data['blob_id'])).fetchone():
                    raise ValueError('Upload the photo first')
            if len(encoded(data).encode()) > 256*1024: raise ValueError('Workout record exceeds 256 KiB')
            now = self.clock()
            revision = db.execute('INSERT INTO changes(user_id,kind,id,deleted,data,at,actor) VALUES(?,?,?,?,?,?,?)',
                (self.user_id, op['kind'], op['id'], op['deleted'], encoded(data), now, actor)).lastrowid
            db.execute('INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?,?)',
                (self.user_id, op['kind'], op['id'], revision, op['deleted'], encoded(data), now))
            result = dict(kind=op['kind'], id=op['id'], revision=revision, deleted=op['deleted'], data=data, updated=now)
            if op['kind'] == 'workout':
                if op['deleted']: db.execute("DELETE FROM trainer WHERE user_id=? AND id=? AND state='queued'",(self.user_id, 'brief_workout_'+op['id']))
                else: self.enqueue_workout_brief(db,op['id'],data,old,revision)
            if op['kind'] == 'sprint' and not op['deleted'] and data.get('status') == 'completed': self.enqueue_sprint_brief(db,op['id'],data)
            db.execute('INSERT INTO mutations VALUES(?,?,?,?)', (self.user_id, op['mutation_id'], request, encoded(result)))
            results.append(result)
            if op['kind'] == 'photo' and op['deleted'] and old and not old['deleted']:
                blob = json.loads(old['data'])['blob_id']
                # Delete original bytes only after the last referencing photo is deleted.
                if not db.execute("SELECT 1 FROM entities WHERE user_id=? AND kind='photo' AND deleted=0 AND json_extract(data,'$.blob_id')=?", (self.user_id, blob)).fetchone():
                    db.execute('DELETE FROM blobs WHERE user_id=? AND id=?', (self.user_id, blob))
        return results

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
            db.execute('INSERT OR REPLACE INTO specialist VALUES(?,1,?,?,?)', (self.user_id, self.clock(), state, detail[:500]))

    def status(self, db=None):
        if db is None:
            with self.db() as conn: return self.status(conn)
        row = db.execute('SELECT * FROM specialist WHERE user_id=? AND id=1', (self.user_id,)).fetchone()
        online = bool(row and self.clock()-row['seen']<90 and row['state'] in ('ready', 'busy'))
        return {'available': online, 'state': row['state'] if online else 'unavailable',
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
            if not self.status(db)['available']: raise Conflict('Workout specialist is unavailable while Codex is offline')
            for photo in photos:
                if not db.execute("SELECT 1 FROM entities WHERE user_id=? AND kind='photo' AND id=? AND deleted=0", (self.user_id, photo)).fetchone():
                    raise ValueError('Selected photo is missing')
            db.execute('INSERT INTO trainer(user_id,id,question,photos,context,created,state) VALUES(?,?,?,?,?,?,?)',
                       (self.user_id, identifier, text, encoded(photos), encoded(context or {}), self.clock(), 'queued'))
        return {'id': identifier, 'state': 'queued'}

    def conversation(self, limit=100, before=None, db=None):
        if not 1 <= limit <= 200: raise ValueError('Invalid conversation limit')
        if db is None:
            with self.db() as conn: return self.conversation(limit,before,conn)
        rows = db.execute("""SELECT * FROM trainer WHERE user_id=? AND (? IS NULL OR created<?)
            AND coalesce(json_extract(context,'$.purpose'),'')!='scheduled_reminder'
            ORDER BY created DESC,rowid DESC LIMIT ?""",
                          (self.user_id, before, before, limit)).fetchall()
        return [{k: json.loads(r[k]) if k in ('photos','context','proposals') and r[k] else r[k]
                 for k in ('id','question','photos','context','created','state','answer','answered_at','proposals','approved')} for r in reversed(rows)]

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
            db.execute("UPDATE trainer SET state='running',token=?,lease_until=? WHERE user_id=? AND id=?",(token, self.clock()+120, self.user_id, row['id']))
            return dict(id=row['id'],question=row['question'],photos=json.loads(row['photos']),context=context,token=token)

    def renew(self, identifier, token):
        with self.db() as db:
            count = db.execute("UPDATE trainer SET lease_until=? WHERE user_id=? AND id=? AND token=? AND state='running' AND lease_until>?",
                               (self.clock()+120, self.user_id, identifier, token, self.clock())).rowcount
            if not count: raise Conflict('Trainer lease lost')

    def finish(self, identifier, token, answer, proposals, state='completed',assessment=None):
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
            changed = db.execute("UPDATE trainer SET answer=?,proposals=?,state=?,answered_at=?,lease_until=NULL WHERE user_id=? AND id=? AND token=? AND state='running' AND lease_until>?",
                (answer, encoded(validated), state, self.clock(), self.user_id, identifier, token, self.clock())).rowcount
            if not changed: raise Conflict('Trainer lease lost')

    def approve(self, identifier):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM trainer WHERE user_id=? AND id=?', (self.user_id, identifier)).fetchone()
            if not row or row['state']!='completed': raise Missing('Completed trainer answer not found')
            proposals = json.loads(row['proposals'] or '[]')
            if not row['approved']: self.check_proposals(db,proposals)
            result = self.mutate(proposals,'approved_trainer_proposal',db)
            db.execute('UPDATE trainer SET approved=1 WHERE user_id=? AND id=?', (self.user_id, identifier))
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

    def enqueue_sprint_brief(self, db, identifier, data):
        """A finished sprint gets one short review of its own, written when the coach is next free."""
        profile=db.execute("SELECT data FROM entities WHERE user_id=? AND kind='athlete' AND deleted=0 ORDER BY updated DESC LIMIT 1", (self.user_id,)).fetchone()
        if not profile or not json.loads(profile['data']).get('auto_coach_briefs'): return
        question=(f"The sprint {data['name']} ({data['start']} to {data['end']}) has ended. Write its brief: at most three short sentences and 45 words: "
                  'what improved, what held back, and the focus for the next sprint. Read its workouts for evidence. No headings, lists or preamble. Do not change the plan or analyse photos.')
        db.execute('INSERT OR IGNORE INTO trainer(user_id,id,question,photos,context,created,state) VALUES(?,?,?,?,?,?,?)',
            (self.user_id, 'brief_sprint_'+identifier, question, '[]', encoded({'purpose':'sprint_brief','automatic':True,'sprint_id':identifier}), self.clock(), 'queued'))

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
            if not self.status(db)['available']: return {'queued':False}
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
                session_id=sprint_id+':'+str(next_item['sequence_number'])+':'+template_id
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
        result=self.question(identifier,'Prepare a concise brief for the next session using the current sprint goals, recent performance and recovery. Do not change the plan or analyse photos.',
            context={'purpose':'next_session_brief','automatic':True,'session_id':session_id,'revision':cursor,
                     'date':when,'sprint_id':sprint_id,'template_id':template_id})
        return {'queued':True,**result}
