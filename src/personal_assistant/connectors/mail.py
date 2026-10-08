"""Resumable Gmail/Graph archive with content hashes and source-qualified records."""
import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from personal_assistant.worker.runtime import NoRedirect


def decode64(data, urlsafe=False):
    data = data.encode() if isinstance(data, str) else data
    return base64.b64decode(data + b'=' * (-len(data) % 4), altchars=b'-_' if urlsafe else None, validate=True)


class OAuthFile:
    """A private token file, never an environment value or command-line secret."""
    def __init__(self, path):
        self.path = Path(path).resolve()
        source = Path(__file__).resolve().parents[3]
        if self.path.is_relative_to(source) or 'onedrive' in str(self.path).casefold():
            raise ValueError('OAuth credentials must be outside the repository and OneDrive.')
        self.opener = urllib.request.build_opener(NoRedirect)

    def token(self):
        auth = json.loads(self.path.read_text())
        if auth.get('access_token') and auth.get('expires_at', 0) > time.time() + 90:
            return auth['access_token']
        provider = auth['provider']
        if provider == 'gmail':
            endpoint = 'https://oauth2.googleapis.com/token'
        elif provider == 'outlook':
            tenant = auth.get('tenant', 'common')
            if not re.fullmatch(r'common|consumers|organizations|[a-fA-F0-9-]{36}', tenant):
                raise ValueError('Invalid Microsoft tenant identifier.')
            endpoint = f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
        else:
            raise ValueError('Unknown mail provider.')
        body = {key: auth[key] for key in ('client_id','refresh_token')}
        body['grant_type'] = 'refresh_token'
        if auth.get('client_secret'):
            body['client_secret'] = auth['client_secret']
        if provider == 'outlook':
            body['scope'] = 'offline_access https://graph.microsoft.com/Mail.Read'
        request = urllib.request.Request(endpoint, data=urllib.parse.urlencode(body).encode(),
            headers={'Content-Type':'application/x-www-form-urlencoded'})
        try:
            with self.opener.open(request, timeout=30) as response:
                fresh = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'OAuth refresh requires attention (HTTP {exc.code}); no mailbox write attempted.') from None
        auth['access_token'] = fresh['access_token']
        auth['expires_at'] = time.time() + fresh['expires_in']
        if fresh.get('refresh_token'):
            auth['refresh_token'] = fresh['refresh_token']
        temporary = self.path.with_suffix('.new')
        temporary.write_text(json.dumps(auth), encoding='utf-8')
        temporary.replace(self.path)
        return auth['access_token']


class MailHTTP:
    def __init__(self, tokens, provider):
        self.tokens, self.provider = tokens, provider
        self.host = 'gmail.googleapis.com' if provider == 'gmail' else 'graph.microsoft.com'
        self.opener = urllib.request.build_opener(NoRedirect)

    def get(self, url, binary=False):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != self.host or parsed.username or parsed.password or parsed.port not in (None,443):
            raise ValueError('Mailbox pagination/attachment URL escaped its provider.')
        for attempt in range(5):
            headers = {'Authorization': 'Bearer ' + self.tokens.token()}
            if self.provider == 'outlook':
                headers['Prefer'] = 'IdType="ImmutableId"'
            try:
                with self.opener.open(urllib.request.Request(url, headers=headers), timeout=45) as response:
                    data = response.read(70 * 1024 * 1024 + 1)
                    if len(data) > 70 * 1024 * 1024:
                        raise ValueError('Attachment exceeds the configured 70 MiB response limit.')
                    return data if binary else json.loads(data)
            except urllib.error.HTTPError as exc:
                if exc.code in (429,500,502,503,504) and attempt < 4:
                    retry = exc.headers.get('Retry-After','')
                    time.sleep(min(60, int(retry) if retry.isdigit() else 2**attempt))
                    continue
                raise RuntimeError(f'Mail API HTTP {exc.code}; checkpoint preserved.') from None
        raise RuntimeError('Mailbox request exhausted retries.')


class Archive:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = self.root / 'catalog.sqlite3'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS messages (
                    account TEXT, id TEXT, path TEXT NOT NULL, complete INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(account,id)
                );
                CREATE TABLE IF NOT EXISTS objects (
                    sha256 TEXT PRIMARY KEY, path TEXT NOT NULL, size INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attachments (
                    account TEXT, message_id TEXT, id TEXT, name TEXT, mime TEXT,
                    sha256 TEXT, category TEXT, status TEXT, source TEXT,
                    PRIMARY KEY(account,message_id,id)
                );
                CREATE TABLE IF NOT EXISTS cursors (account TEXT PRIMARY KEY, url TEXT NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.index, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def complete(self, account, message_id):
        with self.db() as db:
            row = db.execute('SELECT complete FROM messages WHERE account=? AND id=?',(account,message_id)).fetchone()
            return bool(row and row[0])

    def save_message(self, account, message):
        identity = hashlib.sha256((account + ':' + message['id']).encode()).hexdigest()
        path = self.root / 'messages' / (identity + '.json')
        path.parent.mkdir(exist_ok=True)
        temporary = path.with_suffix('.new')
        temporary.write_text(json.dumps(message, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO messages(account,id,path) VALUES(?,?,?)',
                (account,message['id'],str(path.relative_to(self.root))))

    def mark_complete(self, account, message_id):
        with self.db() as db:
            db.execute('UPDATE messages SET complete=1 WHERE account=? AND id=?',(account,message_id))

    def cursor(self, account, url=None, set_value=False):
        with self.db() as db:
            if set_value:
                db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?)',(account,url or ''))
            row = db.execute('SELECT url FROM cursors WHERE account=?',(account,)).fetchone()
            return row[0] if row and row[0] else None

    def attachment(self, account, message_id, attachment_id, name, mime, content, source):
        # Original names are metadata, never path components. Mail content is never executed.
        digest = hashlib.sha256(content).hexdigest() if content is not None else None
        category = 'inbox'  # Categorization needs evidence/review; keep originals unaltered.
        if content is not None:
            path = self.root / 'objects' / digest[:2] / digest
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                temporary = path.with_suffix('.new')
                temporary.write_bytes(content)
                temporary.replace(path)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Existing document object failed its checksum.')
            with self.db() as db:
                db.execute('INSERT OR IGNORE INTO objects VALUES(?,?,?)',
                    (digest,str(path.relative_to(self.root)),len(content)))
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO attachments VALUES(?,?,?,?,?,?,?,?,?)',
                (account,message_id,attachment_id,name,mime,digest,category,
                 'archived' if content is not None else 'linked_requires_access',json.dumps(source)))

    def verify(self):
        failures = []
        with self.db() as db:
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            objects = list(db.execute('SELECT * FROM objects'))
            messages = list(db.execute('SELECT path FROM messages'))
        for row in objects:
            path = (self.root / row['path']).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                failures.append({'sha256': row['sha256'], 'error': 'missing_or_unsafe_path'})
            elif path.stat().st_size != row['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                failures.append({'sha256': row['sha256'], 'error': 'checksum_mismatch'})
        for row in messages:
            path = (self.root / row['path']).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                failures.append({'error': 'message_missing_or_unsafe_path'})
        return {'ok': integrity == 'ok' and not failures, 'sqlite': integrity,
            'objects_checked': len(objects), 'messages_checked': len(messages), 'failures': failures}


def gmail_parts(part):
    if part.get('filename') or part.get('body',{}).get('attachmentId'):
        yield part
    for child in part.get('parts',[]):
        yield from gmail_parts(child)


class GmailCrawler:
    def __init__(self, http, archive, account):
        self.http, self.archive, self.account = http, archive, account

    def scan(self, restart=False):
        first = 'https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=100&includeSpamTrash=true'
        url = None if restart else self.archive.cursor(self.account)
        url = url or first
        count = 0
        while url:
            page = self.http.get(url)
            for item in page.get('messages',[]):
                message_id = item['id']
                if self.archive.complete(self.account,message_id):
                    continue
                endpoint = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/' + urllib.parse.quote(message_id,safe='')
                message = self.http.get(endpoint + '?format=full')
                self.archive.save_message(self.account,message)
                for index, part in enumerate(gmail_parts(message.get('payload',{}))):
                    body = part.get('body',{})
                    attachment_id = body.get('attachmentId') or part.get('partId') or str(index)
                    if body.get('attachmentId'):
                        body = self.http.get(endpoint + '/attachments/' + urllib.parse.quote(body['attachmentId'],safe=''))
                    if 'data' not in body and body.get('size', 0):
                        raise ValueError('Attachment data missing; message left incomplete for retry.')
                    content = decode64(body.get('data',''),True)
                    if 'size' in body and len(content) != body['size']:
                        raise ValueError('Attachment size mismatch; message left incomplete for retry.')
                    self.archive.attachment(self.account,message_id,attachment_id,
                        part.get('filename') or 'unnamed-attachment',part.get('mimeType','application/octet-stream'),content,
                        {'provider':'gmail','account':self.account,'message_id':message_id,'attachment_id':attachment_id,
                         'message_url':'https://mail.google.com/mail/u/0/#all/' + message_id})
                self.archive.mark_complete(self.account,message_id)
                count += 1
            url = first + '&pageToken=' + urllib.parse.quote(page['nextPageToken'],safe='') if page.get('nextPageToken') else None
            self.archive.cursor(self.account,url,True)
        return {'messages_archived_this_run':count,'full_scan_complete':True}


class OutlookCrawler:
    def __init__(self, http, archive, account):
        self.http, self.archive, self.account = http, archive, account

    def scan(self, restart=False):
        # /me/messages spans mailbox folders, including sent/deleted items; archive mailboxes
        # and recoverable/purged stores are separate provider resources, not promised here.
        first = 'https://graph.microsoft.com/v1.0/me/messages?$top=50'
        url = (None if restart else self.archive.cursor(self.account)) or first
        count = 0
        while url:
            page = self.http.get(url)
            for message in page.get('value',[]):
                message_id = message['id']
                if self.archive.complete(self.account,message_id):
                    continue
                self.archive.save_message(self.account,message)
                endpoint = 'https://graph.microsoft.com/v1.0/me/messages/' + urllib.parse.quote(message_id,safe='') + '/attachments'
                attachment_url = endpoint
                # Do not trust hasAttachments: messages with only inline files may say false.
                while attachment_url:
                    attachments = self.http.get(attachment_url)
                    for item in attachments.get('value',[]):
                        kind = item.get('@odata.type','')
                        if kind.endswith('fileAttachment') and 'contentBytes' in item:
                            content = decode64(item['contentBytes'])
                        elif kind.endswith(('fileAttachment','itemAttachment')):
                            content = self.http.get(endpoint + '/' + urllib.parse.quote(item['id'],safe='') + '/$value',True)
                        else:
                            content = None  # Cloud/reference links require separate source permissions.
                        if kind.endswith('fileAttachment') and content is not None and 'size' in item and len(content) != item['size']:
                            raise ValueError('Attachment size mismatch; message left incomplete for retry.')
                        self.archive.attachment(self.account,message_id,item['id'],item.get('name','unnamed-attachment'),
                            item.get('contentType','application/octet-stream'),content,
                            {'provider':'outlook','account':self.account,'message_id':message_id,
                             'attachment_id':item['id'],'message_url':message.get('webLink'),
                             'reference_attachment':kind.endswith('referenceAttachment')})
                    attachment_url = attachments.get('@odata.nextLink')
                self.archive.mark_complete(self.account,message_id)
                count += 1
            url = page.get('@odata.nextLink')
            self.archive.cursor(self.account,url,True)
        return {'messages_archived_this_run':count,'full_scan_complete':True,
            'limits':'Linked/cloud attachments are catalogued separately; archive/recoverable stores need separate access.'}
