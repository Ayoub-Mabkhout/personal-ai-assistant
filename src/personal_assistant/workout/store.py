"""Single-owner cloud workout store with revision conflicts and retry-safe mutations."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
from ..relay.store import Conflict, Missing
from .models import MODELS, Mutation, validate


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Workouts:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS entities(kind TEXT,id TEXT,revision INTEGER NOT NULL,deleted INTEGER NOT NULL,
                data TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS changes(revision INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,id TEXT,
                deleted INTEGER,data TEXT,at REAL,actor TEXT);
            CREATE TABLE IF NOT EXISTS mutations(id TEXT PRIMARY KEY,request TEXT NOT NULL,result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS imports(hash TEXT PRIMARY KEY,report TEXT NOT NULL,raw TEXT NOT NULL,at REAL);
            CREATE TABLE IF NOT EXISTS blobs(id TEXT PRIMARY KEY,mime TEXT NOT NULL,body BLOB NOT NULL,at REAL);
            CREATE TABLE IF NOT EXISTS trainer(id TEXT PRIMARY KEY,question TEXT NOT NULL,photos TEXT NOT NULL,
                context TEXT NOT NULL,created REAL,state TEXT NOT NULL,answer TEXT,proposals TEXT,
                token TEXT,lease_until REAL,approved INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS specialist(id INTEGER PRIMARY KEY CHECK(id=1),seen REAL,state TEXT,detail TEXT);''')
            if 'original' not in {row['name'] for row in db.execute('PRAGMA table_info(imports)')}:
                db.execute('ALTER TABLE imports ADD COLUMN original BLOB')
            if 'answered_at' not in {row['name'] for row in db.execute('PRAGMA table_info(trainer)')}:
                db.execute('ALTER TABLE trainer ADD COLUMN answered_at REAL')

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
            prior = db.execute('SELECT * FROM mutations WHERE id=?', (op['mutation_id'],)).fetchone()
            if prior:
                if prior['request'] != request: raise Conflict('Mutation ID reused with different data')
                results.append(json.loads(prior['result']))
                continue
            old = db.execute('SELECT * FROM entities WHERE kind=? AND id=?', (op['kind'], op['id'])).fetchone()
            if (old['revision'] if old else 0) != op['base_revision']:
                raise Conflict('Stale workout revision: '+op['kind']+'/'+op['id'])
            data = {} if op['deleted'] else validate(op['kind'], op['data'])
            if op['kind'] == 'photo' and not op['deleted']:
                if not db.execute('SELECT 1 FROM blobs WHERE id=?', (data['blob_id'],)).fetchone():
                    raise ValueError('Upload the photo first')
            if len(encoded(data).encode()) > 256*1024: raise ValueError('Workout record exceeds 256 KiB')
            now = self.clock()
            revision = db.execute('INSERT INTO changes(kind,id,deleted,data,at,actor) VALUES(?,?,?,?,?,?)',
                (op['kind'], op['id'], op['deleted'], encoded(data), now, actor)).lastrowid
            db.execute('INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?)',
                (op['kind'], op['id'], revision, op['deleted'], encoded(data), now))
            result = dict(kind=op['kind'], id=op['id'], revision=revision, deleted=op['deleted'], data=data, updated=now)
            db.execute('INSERT INTO mutations VALUES(?,?,?)', (op['mutation_id'], request, encoded(result)))
            results.append(result)
            if op['kind'] == 'photo' and op['deleted'] and old and not old['deleted']:
                blob = json.loads(old['data'])['blob_id']
                # Delete original bytes only after the last referencing photo is deleted.
                if not db.execute("SELECT 1 FROM entities WHERE kind='photo' AND deleted=0 AND json_extract(data,'$.blob_id')=?", (blob,)).fetchone():
                    db.execute('DELETE FROM blobs WHERE id=?', (blob,))
        return results

    @staticmethod
    def row(row):
        return {**dict(row), 'deleted': bool(row['deleted']), 'data': json.loads(row['data'])}

    def get(self, kind, identifier):
        with self.db() as db:
            row = db.execute('SELECT * FROM entities WHERE kind=? AND id=?', (kind, identifier)).fetchone()
            if not row: raise Missing('Workout record not found')
            return self.row(row)

    def list(self, kind=None, offset=0, limit=100):
        if not 1 <= limit <= 200 or offset < 0: raise ValueError('Invalid page')
        with self.db() as db:
            rows = db.execute('SELECT * FROM entities WHERE deleted=0 AND (? IS NULL OR kind=?) ORDER BY updated DESC,id LIMIT ? OFFSET ?',
                              (kind, kind, limit+1, offset)).fetchall()
        return {'items': [self.row(r) for r in rows[:limit]], 'next_offset': offset+limit if len(rows)>limit else None}

    def changes(self, after=0, limit=100):
        if after < 0 or not 1 <= limit <= 200: raise ValueError('Invalid cursor')
        with self.db() as db:
            rows = db.execute('SELECT * FROM changes WHERE revision>? ORDER BY revision LIMIT ?', (after, limit+1)).fetchall()
        items = [self.row(r) for r in rows[:limit]]
        return {'schema_version': 1, 'items': items, 'cursor': items[-1]['revision'] if items else after, 'has_more': len(rows)>limit}

    def export(self):
        with self.db() as db:
            return {'schema_version': 1, 'entities': [self.row(r) for r in db.execute('SELECT * FROM entities ORDER BY kind,id')],
                    'imports': [json.loads(r['report']) for r in db.execute('SELECT report FROM imports ORDER BY at')],
                    'conversation': self.conversation(db=db)}

    def original_import(self, digest):
        with self.db() as db:
            row=db.execute('SELECT original,raw FROM imports WHERE hash=?',(digest,)).fetchone()
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
            if db.execute('SELECT 1 FROM blobs WHERE id=?', (identity,)).fetchone(): return {'id': identity, 'created': False}
            total = db.execute('SELECT coalesce(sum(length(body)),0) FROM blobs').fetchone()[0]
            if total+len(body)>512*1024*1024: raise ValueError('Workout photo storage quota reached')
            db.execute('INSERT INTO blobs VALUES(?,?,?,?)', (identity, mime, body, self.clock()))
        return {'id': identity, 'created': True}

    def blob(self, identity):
        with self.db() as db:
            row = db.execute('SELECT mime,body FROM blobs WHERE id=?', (identity,)).fetchone()
            if not row: raise Missing('Photo not found')
            return row['mime'], row['body']

    def heartbeat(self, state='ready', detail=''):
        if state not in ('ready', 'busy', 'blocked'): raise ValueError('Invalid trainer readiness')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO specialist VALUES(1,?,?,?)', (self.clock(), state, detail[:500]))

    def status(self, db=None):
        if db is None:
            with self.db() as conn: return self.status(conn)
        row = db.execute('SELECT * FROM specialist WHERE id=1').fetchone()
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
            old = db.execute('SELECT * FROM trainer WHERE id=?', (identifier,)).fetchone()
            if old:
                if (old['question'],old['photos'],old['context']) != (text,encoded(photos),encoded(context or {})):
                    raise Conflict('Question ID already used')
                return {'id': identifier, 'state': old['state']}
            if not self.status(db)['available']: raise Conflict('Workout specialist is unavailable while Codex is offline')
            for photo in photos:
                if not db.execute("SELECT 1 FROM entities WHERE kind='photo' AND id=? AND deleted=0", (photo,)).fetchone():
                    raise ValueError('Selected photo is missing')
            db.execute('INSERT INTO trainer(id,question,photos,context,created,state) VALUES(?,?,?,?,?,?)',
                       (identifier,text,encoded(photos),encoded(context or {}),self.clock(),'queued'))
        return {'id': identifier, 'state': 'queued'}

    def conversation(self, limit=100, before=None, db=None):
        if not 1 <= limit <= 200: raise ValueError('Invalid conversation limit')
        if db is None:
            with self.db() as conn: return self.conversation(limit,before,conn)
        rows = db.execute('SELECT * FROM trainer WHERE (? IS NULL OR created<?) ORDER BY created DESC,rowid DESC LIMIT ?',
                          (before,before,limit)).fetchall()
        return [{k: json.loads(r[k]) if k in ('photos','context','proposals') and r[k] else r[k]
                 for k in ('id','question','photos','context','created','state','answer','answered_at','proposals','approved')} for r in reversed(rows)]

    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM trainer WHERE state='running' AND lease_until>?",(self.clock(),)).fetchone(): return None
            row = db.execute("SELECT * FROM trainer WHERE state='queued' OR (state='running' AND lease_until<=?) ORDER BY created,rowid LIMIT 1",(self.clock(),)).fetchone()
            if not row: return None
            token = secrets.token_urlsafe(24)
            db.execute("UPDATE trainer SET state='running',token=?,lease_until=? WHERE id=?",(token,self.clock()+120,row['id']))
            return dict(id=row['id'],question=row['question'],photos=json.loads(row['photos']),context=json.loads(row['context']),token=token)

    def renew(self, identifier, token):
        with self.db() as db:
            count = db.execute("UPDATE trainer SET lease_until=? WHERE id=? AND token=? AND state='running' AND lease_until>?",
                               (self.clock()+120,identifier,token,self.clock())).rowcount
            if not count: raise Conflict('Trainer lease lost')

    def finish(self, identifier, token, answer, proposals, state='completed',assessment=None):
        if state not in ('completed','failed'): raise ValueError('Invalid outcome')
        if not isinstance(answer,str) or not 1<=len(answer)<=24000 or len(proposals)>20: raise ValueError('Invalid specialist response')
        validated = [Mutation.model_validate(p).model_dump() for p in proposals]
        # Specialist proposals are limited to future planning, not rewrites of history.
        for p in validated:
            if p['kind'] not in ('template','sprint','workout'): raise ValueError('Unknown trainer proposal kind')
            if not p['deleted']: validate(p['kind'],p['data'])
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM trainer WHERE id=?',(identifier,)).fetchone()
            if (prior and prior['state']==state and prior['token']==token
                    and prior['answer']==answer and prior['proposals']==encoded(validated)):
                return
            job = db.execute("SELECT * FROM trainer WHERE id=? AND token=? AND state='running' AND lease_until>?",(identifier,token,self.clock())).fetchone()
            if not job: raise Conflict('Trainer lease lost')
            self.check_proposals(db,validated)
            if assessment:
                if state!='completed': raise ValueError('Failed jobs cannot save estimates')
                allowed = json.loads(job['photos'])
                data = validate('composition',assessment)
                if data['source_question']!=identifier or not set(data['photo_ids'])<=set(allowed):
                    raise ValueError('Photo analysis was not approved for these images')
                for photo in data['photo_ids']:
                    if not db.execute("SELECT 1 FROM entities WHERE kind='photo' AND id=? AND deleted=0",(photo,)).fetchone():
                        raise ValueError('An approved photo was deleted during analysis')
                self.mutate([dict(mutation_id=hashlib.sha256(('assessment:'+identifier).encode()).hexdigest(),kind='composition',id=identifier,base_revision=0,data=data)],'approved_photo_analysis',db)
            changed = db.execute("UPDATE trainer SET answer=?,proposals=?,state=?,answered_at=?,lease_until=NULL WHERE id=? AND token=? AND state='running' AND lease_until>?",
                (answer,encoded(validated),state,self.clock(),identifier,token,self.clock())).rowcount
            if not changed: raise Conflict('Trainer lease lost')

    def approve(self, identifier):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM trainer WHERE id=?', (identifier,)).fetchone()
            if not row or row['state']!='completed': raise Missing('Completed trainer answer not found')
            proposals = json.loads(row['proposals'] or '[]')
            if not row['approved']: self.check_proposals(db,proposals)
            result = self.mutate(proposals,'approved_trainer_proposal',db)
            db.execute('UPDATE trainer SET approved=1 WHERE id=?', (identifier,))
            return {'approved': True, 'results': result}

    def check_proposals(self, db, proposals):
        for p in proposals:
            row=db.execute('SELECT * FROM entities WHERE kind=? AND id=?',(p['kind'],p['id'])).fetchone()
            if (row['revision'] if row else 0)!=p['base_revision']:
                raise Conflict('Record changed while trainer was responding')
            if p['deleted'] and (not row or row['deleted']): raise ValueError('Cannot delete a missing workout record')
            if not p['deleted']: validate(p['kind'],p['data'])

    def next_session_brief(self):
        with self.db() as db:
            row=db.execute("SELECT * FROM trainer WHERE state='completed' AND json_extract(context,'$.purpose')='next_session_brief' ORDER BY answered_at DESC,rowid DESC LIMIT 1").fetchone()
            if not row:
                return {'text':None,'generated_at':None,'session_id':None,
                        'status':'missing' if self.status(db)['available'] else 'unavailable'}
            context=json.loads(row['context']);at=row['answered_at'] or row['created']
            cursor=db.execute('SELECT coalesce(max(revision),0) FROM changes').fetchone()[0]
            stale=self.clock()-at>86400 or context.get('revision')!=cursor
            return {'text':row['answer'],'generated_at':at,'session_id':context.get('session_id'),
                    'status':'stale' if stale else 'cached','specialist_available':self.status(db)['available']}

    def prepare_brief(self, timezone='UTC'):
        """Owner-opted-in, debounced ahead-of-session preparation. Never uses photos."""
        from datetime import datetime,date
        from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
        from .analytics import scheduled_day
        try: today=datetime.fromtimestamp(self.clock(),ZoneInfo(timezone)).date().isoformat()
        except (ValueError,ZoneInfoNotFoundError): raise ValueError('Unknown brief timezone') from None
        with self.db() as db:
            if not self.status(db)['available']: return {'queued':False}
            rows=[self.row(r) for r in db.execute('SELECT * FROM entities WHERE deleted=0')]
            profiles=[r for r in rows if r['kind']=='athlete']
            if not profiles or not max(profiles,key=lambda r:r['updated'])['data'].get('auto_coach_briefs'):
                return {'queued':False}
            if db.execute("SELECT 1 FROM trainer WHERE state IN ('queued','running')").fetchone(): return {'queued':False}
            if not rows or self.clock()-max(r['updated'] for r in rows)<120: return {'queued':False}
            # Only future scheduled work; an ongoing workout is never interrupted by auto-coaching.
            if any(r['kind']=='workout' and r['data']['status'] in ('active','paused') for r in rows): return {'queued':False}
            from .programs import next_workout
            next_item=next_workout(rows,date.fromisoformat(today))
            if next_item:
                sprint_id=next_item['sprint_id'];template_id=next_item['template_id'];when=today
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
            previous=db.execute("SELECT created FROM trainer WHERE json_extract(context,'$.automatic')=1 AND json_extract(context,'$.session_id')=? ORDER BY created DESC LIMIT 1",(session_id,)).fetchone()
            if previous and self.clock()-previous['created']<21600: return {'queued':False}
            # Include exact revisions, so retries cannot duplicate an identical brief.
            signature=hashlib.sha256(encoded(sorted((r['kind'],r['id'],r['revision']) for r in rows)).encode()).hexdigest()
            identifier='brief_'+signature
            if db.execute('SELECT 1 FROM trainer WHERE id=?',(identifier,)).fetchone(): return {'queued':False}
            cursor=db.execute('SELECT coalesce(max(revision),0) FROM changes').fetchone()[0]
        result=self.question(identifier,'Prepare a concise brief for the next session using the current sprint goals, recent performance and recovery. Do not change the plan or analyse photos.',
            context={'purpose':'next_session_brief','automatic':True,'session_id':session_id,'revision':cursor,
                     'date':when,'sprint_id':sprint_id,'template_id':template_id})
        return {'queued':True,**result}
