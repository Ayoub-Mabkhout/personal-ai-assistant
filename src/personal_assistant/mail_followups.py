"""Private, source-qualified email obligations; no calendar or mailbox writes."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from email.utils import getaddresses
from personal_assistant.email_index import MailIndex


KINDS = {'deadline', 'renewal', 'awaiting_reply'}


class Followups:
    def __init__(self, path, archive, policy=None):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.index = MailIndex(archive, policy)
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS followups(id TEXT PRIMARY KEY, account TEXT,
                thread_id TEXT, topic TEXT, kind TEXT, title TEXT, state TEXT,
                certainty TEXT, due_date TEXT, data TEXT, updated_at TEXT);
              CREATE TABLE IF NOT EXISTS followup_history(id INTEGER PRIMARY KEY,
                followup_id TEXT, at TEXT, action TEXT, data TEXT);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def record(self, account, item):
        """Require an exact source excerpt before persisting model-derived claims."""
        self.index.allowed(account)
        self.index.refresh()
        kind = item.get('kind')
        if kind not in KINDS: raise ValueError('Unknown follow-up kind.')
        title = str(item.get('title') or '').strip()
        topic = str(item.get('topic') or title).strip().casefold()
        if not title or len(title)>500 or not topic or len(topic)>500:
            raise ValueError('A concise title and stable topic are required.')
        message_id = item.get('message_id')
        quote = str(item.get('quote') or '').strip()
        source = self.index.read(account, message_id)
        if not quote or len(quote)>4000 or quote not in source['body']:
            raise ValueError('Evidence must be an exact excerpt from the saved live message.')
        certainty = item.get('certainty', 'tentative')
        if certainty not in ('tentative', 'confirmed'): raise ValueError('Invalid certainty.')
        due = item.get('due_date') or None
        if due:
            due = date.fromisoformat(due).isoformat()
            # A date interpretation remains tentative unless explicit wording is cited.
            date_evidence = str(item.get('date_evidence') or '').strip()
            if certainty=='confirmed' and (not date_evidence or date_evidence not in quote):
                raise ValueError('Confirmed dates require explicit date wording in the evidence.')
        if kind=='awaiting_reply':
            addresses = {value.casefold() for _,value in getaddresses([source['sender']])}
            if account.casefold() not in addresses:
                raise ValueError('Awaiting a reply must originate in the owner\'s sent message.')
            checked = item.get('context_message_ids') or []
            if message_id not in checked: raise ValueError('The checked thread context is required.')
            latest = None
            for identity in checked:
                other = self.index.read(account, identity)
                if other['thread_id']!=source['thread_id']: raise ValueError('Thread context IDs differ.')
                if not other['sent']: raise ValueError('Thread message ordering is unknown; awaiting reply remains unverified.')
                if latest is None or other['sent']>latest['sent']: latest=other
                elif other['sent']==latest['sent'] and account.casefold() not in {value.casefold() for _,value in getaddresses([other['sender']])}: latest=other
            if account.casefold() not in {value.casefold() for _,value in getaddresses([latest['sender']])}:
                raise ValueError('An incoming reply exists in the checked context; resolve or reassess it.')
            # Absence of a reply is a current observation, not a guaranteed future fact.
            certainty = 'tentative'
        identity = hashlib.sha256(json.dumps([account.casefold(),source['thread_id'],kind,topic]).encode()).hexdigest()[:24]
        now = datetime.now(timezone.utc).isoformat()
        data = {**item, 'account':account, 'message_id':message_id, 'thread_id':source['thread_id'],
                'quote':quote, 'source_url':source.get('source_url') or self._url(account,message_id),
                'checked_at':now, 'certainty':certainty, 'due_date':due}
        encoded=json.dumps(data,ensure_ascii=False,sort_keys=True)
        with self.db() as db:
            old=db.execute('SELECT state,data FROM followups WHERE id=?',(identity,)).fetchone()
            state=old['state'] if old else 'open'  # Never reopen dismissed/resolved records on a rescan.
            db.execute('''INSERT INTO followups VALUES(?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET title=excluded.title,certainty=excluded.certainty,
                due_date=excluded.due_date,data=excluded.data,updated_at=excluded.updated_at''',
                (identity,account,source['thread_id'],topic,kind,title,state,certainty,due,encoded,now))
            db.execute('INSERT INTO followup_history(followup_id,at,action,data) VALUES(?,?,?,?)',
                (identity,now,'observed',encoded))
        return self.get(identity)

    def _url(self, account, identity):
        # Source link is present in the archive for Gmail and Graph; fallback stays local.
        with self.index.db() as db:
            row=db.execute('SELECT source FROM mail WHERE account=? AND id=?',(account,identity)).fetchone()
        if not row: return None
        message=json.loads(Path(row['source']).read_text(encoding='utf-8'))
        return message.get('webLink') or 'https://mail.google.com/mail/u/0/#all/'+identity

    def get(self, identity):
        with self.db() as db: row=db.execute('SELECT * FROM followups WHERE id=?',(identity,)).fetchone()
        if not row: raise KeyError(identity)
        result=dict(row);result['data']=json.loads(result['data'])
        return result

    def list(self, state='open', before=None):
        conditions=[];args=[]
        if state:
            if state not in ('open','resolved','dismissed'): raise ValueError('Invalid state.')
            conditions.append('state=?');args.append(state)
        if before:
            date.fromisoformat(before);conditions.append('due_date<=?');args.append(before)
        with self.db() as db:
            sql='SELECT id FROM followups'+(' WHERE '+' AND '.join(conditions) if conditions else '')+' ORDER BY due_date IS NULL,due_date,updated_at DESC'
            ids=[row['id'] for row in db.execute(sql,args)]
        records=[]
        for identity in ids:
            record=self.get(identity)
            try: self.index.allowed(record['account'])
            except ValueError: continue
            records.append(record)
        return records

    def set_state(self, identity, state, note=''):
        if state not in ('open','resolved','dismissed'): raise ValueError('Invalid state.')
        self.index.allowed(self.get(identity)['account'])
        now=datetime.now(timezone.utc).isoformat()
        with self.db() as db:
            if not db.execute('SELECT id FROM followups WHERE id=?',(identity,)).fetchone(): raise KeyError(identity)
            db.execute('UPDATE followups SET state=?,updated_at=? WHERE id=?',(state,now,identity))
            db.execute('INSERT INTO followup_history(followup_id,at,action,data) VALUES(?,?,?,?)',
                (identity,now,state,json.dumps({'note':note},ensure_ascii=False)))
        return self.get(identity)
