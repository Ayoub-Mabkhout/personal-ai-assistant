"""Incremental, source-qualified keyword index for archived email, not live mail."""
from contextlib import contextmanager
from datetime import datetime,timezone
from email.utils import getaddresses,parsedate_to_datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
from personal_assistant.connectors.mail import decode64


class PlainHTML(HTMLParser):
    def __init__(self): super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.hidden+=1
        elif tag in ('p','br','div','li','tr'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)


def normalize(message):
    payload=message.get('payload') or {}
    headers={row['name'].lower():row.get('value','') for row in payload.get('headers') or [] if isinstance(row,dict) and row.get('name')}
    graph=not bool(payload)
    subject=message.get('subject') if graph else headers.get('subject','')
    sender=(message.get('from') or {}).get('emailAddress',{}) if graph else {}
    sender=(sender.get('name','')+' <'+sender.get('address','')+'>') if graph else headers.get('from','')
    recipients=[row.get('emailAddress',{}).get('address','') for row in message.get('toRecipients',[])] if graph else [address for _,address in getaddresses([headers.get('to',''),headers.get('cc','')])]
    date=message.get('receivedDateTime') or message.get('sentDateTime') or headers.get('date','')
    try:
        if message.get('internal_date') or message.get('internalDate'):
            sent=datetime.fromtimestamp(int(message.get('internal_date',message.get('internalDate')))/1000,timezone.utc).isoformat()
        elif graph: sent=datetime.fromisoformat(date.replace('Z','+00:00')).astimezone(timezone.utc).isoformat()
        else: sent=parsedate_to_datetime(date).astimezone(timezone.utc).isoformat()
    except (ValueError,TypeError,OverflowError): sent=''
    plain=[];html=[]
    def walk(part):
        mime=part.get('mime_type',part.get('mimeType',''));body=part.get('body') or {}
        if mime in ('text/plain','text/html') and not part.get('filename'):
            text=body.get('content')
            encoded=body.get('base64_url_content') or body.get('data')
            if text is None and encoded:
                try: text=decode64(encoded,True).decode('utf-8',errors='replace')
                except ValueError: text=''
            if isinstance(text,str): (plain if mime=='text/plain' else html).append(text)
        for child in part.get('parts') or []: walk(child)
    if graph:
        body=message.get('body') or {}
        (html if body.get('contentType','').casefold()=='html' else plain).append(body.get('content',''))
    else: walk(payload)
    if not plain and html:
        parser=PlainHTML();parser.feed('\n'.join(html));plain=[''.join(parser.parts)]
    body='\n'.join(plain) or message.get('snippet','') or message.get('bodyPreview','')
    return {'thread_id':message.get('thread_id',message.get('threadId',message.get('conversationId',message['id']))),
        'subject':subject or '', 'norm_subject':re.sub(r'^(?:(?:re|fw|fwd|aw):\s*)+','',subject or '',flags=re.I).casefold(),
        'sender':sender,'recipients':', '.join(value for value in recipients if value),'sent':sent,'body':body[:2000000],
        'message_header':headers.get('message-id',''),'reply_header':headers.get('in-reply-to',''),
        'refs':headers.get('references',''),'body_truncated':len(body)>2000000}


class MailIndex:
    def __init__(self,archive,policy=None):
        self.root=Path(archive).resolve();self.catalog=self.root/'catalog.sqlite3'
        self.policy=Path(policy) if policy else Path(__file__).resolve().parents[2]/'private/auth/mail-connections.json'
        self.excluded=set()
        if self.policy.is_file():
            self.excluded={item['account'].casefold() for item in json.loads(self.policy.read_text(encoding='utf-8')).get('excluded_accounts',[])}
        self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'query-index.sqlite3'
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS mail(account TEXT,id TEXT,thread_id TEXT,subject TEXT,norm_subject TEXT,
                sender TEXT,recipients TEXT,sent TEXT,body TEXT,message_header TEXT,reply_header TEXT,refs TEXT,
                source TEXT,size INTEGER,mtime INTEGER,body_truncated INTEGER,PRIMARY KEY(account,id));
              CREATE INDEX IF NOT EXISTS mail_thread ON mail(account,thread_id,sent);
              CREATE INDEX IF NOT EXISTS mail_sent ON mail(sent);
              CREATE VIRTUAL TABLE IF NOT EXISTS keywords USING fts5(subject,body,sender);
            ''')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=20);db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def allowed(self,account):
        if account and account.casefold() in self.excluded: raise ValueError('This account is excluded by the user.')

    def refresh(self):
        if not self.catalog.is_file(): return 0
        source=sqlite3.connect(self.catalog.resolve().as_uri()+'?mode=ro',uri=True);source.row_factory=sqlite3.Row
        try: rows=list(source.execute('SELECT account,id,path FROM messages'))
        finally: source.close()
        count=0
        with self.db() as db:
            for row in rows:
                if row['account'].casefold() in self.excluded: continue
                path=(self.root/row['path']).resolve()
                if not path.is_relative_to(self.root) or not path.is_file(): raise ValueError('Unsafe or missing archived message path')
                stat=path.stat()
                old=db.execute('SELECT rowid,size,mtime FROM mail WHERE account=? AND id=?',(row['account'],row['id'])).fetchone()
                if old and old['size']==stat.st_size and old['mtime']==stat.st_mtime_ns: continue
                data=normalize(json.loads(path.read_text(encoding='utf-8')))
                if old: db.execute('DELETE FROM keywords WHERE rowid=?',(old['rowid'],))
                columns=['account','id',*data.keys(),'source','size','mtime']
                values=[row['account'],row['id'],*data.values(),str(path),stat.st_size,stat.st_mtime_ns]
                updates=','.join(name+'=excluded.'+name for name in columns[2:])
                db.execute('INSERT INTO mail('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+') ON CONFLICT(account,id) DO UPDATE SET '+updates,values)
                identity=db.execute('SELECT rowid FROM mail WHERE account=? AND id=?',(row['account'],row['id'])).fetchone()[0]
                db.execute('INSERT INTO keywords(rowid,subject,body,sender) VALUES(?,?,?,?)',(identity,data['subject'],data['body'],data['sender']))
                count+=1
        return count

    def coverage(self):
        with self.db() as db:
            rows=[dict(row) for row in db.execute('SELECT account,COUNT(*) AS messages,MIN(sent) AS first_date,MAX(sent) AS last_date FROM mail GROUP BY account') if row['account'].casefold() not in self.excluded]
        return {'mode':'local_archive_snapshot','accounts':rows,'complete_mailbox':False,
                'note':'The archive may omit whole threads or newer messages. A local miss is not proof of absence in live mail.'}

    def search(self,account=None,subject=None,sender=None,to=None,since=None,before=None,text=None,limit=20):
        self.allowed(account);conditions=[];values=[]
        if not 1<=limit<=100: raise ValueError('Limit must be 1-100')
        if account: conditions.append('m.account=?');values.append(account)
        for column,value in [('subject',subject),('sender',sender),('recipients',to)]:
            if value: conditions.append('m.'+column+' LIKE ?');values.append('%'+value+'%')
        for operator,value in [('>=',since),('<',before)]:
            if value:
                datetime.fromisoformat(value)
                conditions.append('m.sent'+operator+'?');values.append(value)
        join=''
        if text:
            tokens=re.findall(r'\w+',text,re.UNICODE)
            if not tokens: return []
            join=' JOIN keywords ON keywords.rowid=m.rowid'
            conditions.append('keywords MATCH ?');values.append(' AND '.join('"'+token+'"' for token in tokens))
        for excluded in self.excluded: conditions.append('lower(m.account)!=?');values.append(excluded)
        sql='SELECT m.account,m.id,m.thread_id,m.subject,m.sender,m.recipients,m.sent,substr(m.body,1,350) AS preview,m.source FROM mail m'+join
        if conditions: sql+=' WHERE '+' AND '.join(conditions)
        sql+=' ORDER BY m.sent DESC LIMIT ?';values.append(limit)
        with self.db() as db: return [dict(row) for row in db.execute(sql,values)]

    def read(self,account,identifier):
        self.allowed(account)
        with self.db() as db: row=db.execute('SELECT * FROM mail WHERE account=? AND id=?',(account,identifier)).fetchone()
        if not row: raise ValueError('Message is not present in the local snapshot')
        result=dict(row)
        db=sqlite3.connect(self.catalog.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            db.row_factory=sqlite3.Row
            result['attachments']=[dict(row) for row in db.execute('SELECT id,name,mime,status,sha256,category FROM attachments WHERE account=? AND message_id=?',(account,identifier))]
        finally: db.close()
        return result

    def thread(self,account,identifier):
        self.allowed(account)
        with self.db() as db: ids=[row['id'] for row in db.execute('SELECT id FROM mail WHERE account=? AND thread_id=? ORDER BY sent,id',(account,identifier))]
        return [self.read(account,value) for value in ids]

    def related(self,account,identifier,limit=20):
        if not 1<=limit<=100: raise ValueError('Limit must be 1-100')
        base=self.read(account,identifier)
        participants=[address for _,address in getaddresses([base['sender'],base['recipients']]) if address.casefold()!=account.casefold()]
        terms=[term for term in re.findall(r'\w+',base['norm_subject']) if len(term)>3]
        with self.db() as db:
            rows=list(db.execute('SELECT account,id,thread_id,subject,norm_subject,sender,recipients,sent,refs,reply_header,message_header,source FROM mail WHERE account=? AND thread_id!=? ORDER BY sent DESC',(account,base['thread_id'])))
        matches=[]
        for row in rows:
            reasons=[]
            if base['message_header'] and base['message_header'] in (row['refs']+' '+row['reply_header']): reasons.append('reply/reference link')
            if row['message_header'] and row['message_header'] in (base['refs']+' '+base['reply_header']): reasons.append('referenced earlier message')
            if row['norm_subject']==base['norm_subject'] and base['norm_subject']: reasons.append('same topic with a different thread ID')
            shared=any(person in (row['sender']+' '+row['recipients']) for person in participants)
            if shared and any(term in row['norm_subject'] for term in terms): reasons.append('shared participant and topic')
            if reasons: matches.append({**dict(row),'reasons':reasons})
            if len(matches)>=limit: break
        return matches
