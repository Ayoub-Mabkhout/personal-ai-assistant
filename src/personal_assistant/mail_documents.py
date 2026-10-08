"""Save source-qualified email originals and deterministic classified vault copies."""
from datetime import date
from email import policy
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote,urlsplit
import urllib.request
from personal_assistant.worker.runtime import NoRedirect
from personal_assistant.connectors.mail import Archive,MailHTTP,OAuthFile,decode64
from personal_assistant.email_index import MailIndex,normalize


CATEGORIES={'inbox','contracts','banking/statements','tax','insurance','housing',
    'identity','health','academic/thesis','academic/coursework','career/cvs',
    'career/cover-letters','career/applications','work','receipts','archive'}


def slug(value,fallback):
    value=unicodedata.normalize('NFKD',value.replace('ß','ss')).encode('ascii','ignore').decode()
    return re.sub(r'[^a-z0-9]+','-',value.casefold()).strip('-')[:45] or fallback


class MailDocuments:
    def __init__(self,archive,vault,policy=None):
        self.archive=Archive(archive);self.vault=Path(vault).resolve()
        self.policy=MailIndex(archive,policy)
        with self.archive.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS document_copies(
                account TEXT,message_id TEXT,attachment_id TEXT,category TEXT,sha256 TEXT,
                path TEXT NOT NULL,provenance TEXT NOT NULL,
                PRIMARY KEY(account,message_id,attachment_id,category,sha256))''')

    def attachment(self,account,message_id,attachment_id):
        self.policy.allowed(account)
        with self.archive.db() as db:
            row=db.execute('SELECT * FROM attachments WHERE account=? AND message_id=? AND id=?',
                (account,message_id,attachment_id)).fetchone()
        if not row: raise ValueError('Read the parent message and catalogue its actual attachment before filing it.')
        return dict(row)

    def catalog_message(self,account,message):
        """Import a live Gmail MIME or Graph message without marking its mailbox complete."""
        self.policy.allowed(account)
        self.archive.save_message(account,message)
        def parts(part):
            yield part
            for child in part.get('parts') or []: yield from parts(child)
        count=0
        for part in parts(message.get('payload') or {}):
            if not part.get('filename'): continue
            body=part.get('body') or {}
            identity=body.get('attachment_id') or body.get('attachmentId') or part.get('part_id') or part.get('partId')
            if not identity: continue # A filename is not a provider attachment ID.
            with self.archive.db() as db:
                old=db.execute('SELECT sha256 FROM attachments WHERE account=? AND message_id=? AND id=?',
                    (account,message['id'],identity)).fetchone()
            if old and old['sha256']: continue # Keep previously acquired originals.
            source={'provider':'gmail','account':account,'message_id':message['id'],'attachment_id':identity,
                'message_url':'https://mail.google.com/mail/u/0/#all/'+message['id'],'expected_size':body.get('size')}
            encoded=body.get('data') or body.get('base64_url_content')
            content=decode64(encoded,True) if encoded else None
            if content is not None and body.get('size') is not None and len(content)!=body['size']:
                raise ValueError('Embedded original attachment size mismatch.')
            self.archive.attachment(account,message['id'],identity,part['filename'],
                part.get('mime_type',part.get('mimeType','application/octet-stream')),content,source)
            count+=1
        return count

    def fetch(self,account,message_id,attachment_id,provider,credentials):
        """Optional independent OAuth path; never harvest the desktop connector's tokens."""
        row=self.attachment(account,message_id,attachment_id)
        tokens=OAuthFile(credentials)
        metadata=json.loads(tokens.path.read_text(encoding='utf-8'))
        if metadata.get('provider')!=provider or metadata.get('account_email','').casefold()!=account.casefold():
            raise ValueError('OAuth metadata does not match the requested provider/account.')
        http=MailHTTP(tokens,provider)
        if provider=='gmail':
            base='https://gmail.googleapis.com/gmail/v1/users/me'
            if http.get(base+'/profile').get('emailAddress','').casefold()!=account.casefold():
                raise ValueError('Authorized Gmail identity differs from the requested account.')
            endpoint=base+'/messages/'+quote(message_id,safe='')
            message=http.get(endpoint+'?format=full')
            def parts(part):
                yield part
                for child in part.get('parts') or []: yield from parts(child)
            candidates=[part for part in parts(message.get('payload') or {})
                if (part.get('body') or {}).get('attachmentId')==attachment_id
                or (part.get('partId')==attachment_id and part.get('filename'))]
            if len(candidates)!=1: raise ValueError('Attachment ID is not unique in the live parent message.')
            part=candidates[0];body=part.get('body') or {}
            if body.get('attachmentId'):
                body=http.get(endpoint+'/attachments/'+quote(body['attachmentId'],safe=''))
            if 'data' not in body: raise ValueError('Original attachment bytes are missing.')
            content=decode64(body['data'],True)
            if body.get('size') is not None and len(content)!=body['size']: raise ValueError('Attachment size mismatch.')
            name=part.get('filename') or row['name'];mime=part.get('mimeType') or row['mime']
            source={'provider':provider,'account':account,'message_id':message_id,'attachment_id':attachment_id,
                    'message_url':'https://mail.google.com/mail/u/0/#all/'+message_id}
        elif provider=='outlook':
            base='https://graph.microsoft.com/v1.0/me'
            identity=http.get(base+'?$select=mail,userPrincipalName')
            if account.casefold() not in {str(identity.get(key) or '').casefold() for key in ('mail','userPrincipalName')}:
                raise ValueError('Authorized Outlook identity differs from the requested account.')
            endpoint=base+'/messages/'+quote(message_id,safe='')
            message=http.get(endpoint)
            attachment_url=endpoint+'/attachments/'+quote(attachment_id,safe='')
            part=http.get(attachment_url)
            kind=part.get('@odata.type','')
            if kind.endswith('referenceAttachment'): raise ValueError('Reference attachment requires its own authorized source; no original bytes saved.')
            if kind.endswith('fileAttachment') and 'contentBytes' in part: content=decode64(part['contentBytes'])
            elif kind.endswith(('fileAttachment','itemAttachment')): content=http.get(attachment_url+'/$value',True)
            else: raise ValueError('Unsupported Outlook attachment type.')
            if kind.endswith('fileAttachment') and part.get('size') is not None and len(content)!=part['size']:
                raise ValueError('Attachment size mismatch.')
            name=part.get('name') or row['name'];mime=part.get('contentType') or row['mime']
            source={'provider':provider,'account':account,'message_id':message_id,'attachment_id':attachment_id,'message_url':message.get('webLink')}
        else: raise ValueError('Unknown mail provider.')
        self.archive.save_message(account,message)
        self.archive.attachment(account,message_id,attachment_id,name,mime,content,source)
        return self.attachment(account,message_id,attachment_id)

    def import_original(self,account,message_id,attachment_id,path):
        row=self.attachment(account,message_id,attachment_id)
        path=Path(path).resolve()
        if not path.is_file() or path.stat().st_size>70*1024*1024: raise ValueError('Missing original or file exceeds 70 MiB.')
        content=path.read_bytes()
        source=json.loads(row['source']);source['original_import_path']=str(path)
        if source.get('expected_size') is not None and len(content)!=source['expected_size']:
            raise ValueError('Imported original size differs from the live MIME metadata.')
        if row['sha256'] and hashlib.sha256(content).hexdigest()!=row['sha256']:
            raise ValueError('Imported original differs from the source already archived.')
        self.archive.attachment(account,message_id,attachment_id,row['name'],row['mime'],content,source)

    def import_artifact(self,account,message_id,attachment_id,artifact):
        """Download a Gmail tool's signed original artifact; do not confuse it with extraction."""
        row=self.attachment(account,message_id,attachment_id)
        if artifact.get('message_id')!=message_id or artifact.get('attachment_id')!=attachment_id:
            raise ValueError('Artifact source IDs differ from the requested attachment.')
        uri=artifact.get('file_uri')
        url=uri.get('download_url') if isinstance(uri,dict) else uri
        parsed=urlsplit(url or '')
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.oaiusercontent.com') or parsed.username or parsed.password or parsed.port not in (None,443):
            raise ValueError('Missing or unexpected original artifact download URL.')
        with urllib.request.build_opener(NoRedirect).open(url,timeout=45) as response:
            content=response.read(70*1024*1024+1)
        if len(content)>70*1024*1024: raise ValueError('Original artifact exceeds 70 MiB.')
        if artifact.get('size_bytes') is not None and len(content)!=artifact['size_bytes']:
            raise ValueError('Artifact size differs from connector metadata.')
        if row['sha256'] and hashlib.sha256(content).hexdigest()!=row['sha256']:
            raise ValueError('Original artifact differs from the archived source.')
        source=json.loads(row['source'])
        source['connector_file_id']=uri.get('file_id') if isinstance(uri,dict) else artifact.get('file_id')
        source['acquisition']='authorized_connector_original_artifact'
        self.archive.attachment(account,message_id,attachment_id,row['name'],row['mime'],content,source)

    def import_raw_message(self,account,message_id,attachment_id,message):
        """Extract exact original bytes from the authorized Gmail API raw representation."""
        row=self.attachment(account,message_id,attachment_id)
        if message.get('id')!=message_id or not isinstance(message.get('raw'),str):
            raise ValueError('Raw Gmail response does not match the requested message.')
        if len(message['raw'])>94*1024*1024: raise ValueError('Raw message exceeds the 70 MiB decoded limit.')
        raw=decode64(message['raw'],True)
        if len(raw)>70*1024*1024: raise ValueError('Raw message exceeds 70 MiB.')
        parsed=BytesParser(policy=policy.default).parsebytes(raw)
        matches=[part for part in parsed.walk() if part.get_filename()==row['name']]
        if len(matches)!=1: raise ValueError('Selected filename is not unique in the original MIME message.')
        part=matches[0];content=part.get_payload(decode=True)
        if not isinstance(content,bytes): raise ValueError('Selected MIME part has no original bytes.')
        source=json.loads(row['source'])
        if source.get('expected_size') is not None and len(content)!=source['expected_size']:
            raise ValueError('Original MIME attachment size differs from live metadata.')
        digest=hashlib.sha256(content).hexdigest()
        if row['sha256'] and digest!=row['sha256']: raise ValueError('MIME original differs from previously saved source bytes.')
        raw_digest=hashlib.sha256(raw).hexdigest()
        raw_path=self.archive.root/'raw-messages'/(raw_digest+'.eml')
        raw_path.parent.mkdir(exist_ok=True)
        try:
            with raw_path.open('xb') as stream: stream.write(raw)
        except FileExistsError:
            if hashlib.sha256(raw_path.read_bytes()).hexdigest()!=raw_digest: raise ValueError('Original raw message checksum mismatch.')
        source.update(acquisition='authorized_gmail_api_raw_message',raw_message_path=str(raw_path),raw_message_sha256=raw_digest)
        self.archive.attachment(account,message_id,attachment_id,row['name'],part.get_content_type(),content,source)

    def import_raw_trace(self,account,message_id,attachment_id,trace):
        """Read the worker's own captured tool result, avoiding model copying of base64."""
        found=None
        with Path(trace).open(encoding='utf-8') as stream:
            for line in stream:
                try: event=json.loads(line)
                except ValueError: continue # The final trace line may still be streaming.
                item=event.get('item') or {}
                if event.get('type')!='item.completed' or item.get('tool')!='gmail.read_email': continue
                message=(item.get('result') or {}).get('structured_content') or {}
                if message.get('id')==message_id and message.get('raw'): found=message
        if not found: raise ValueError('No successful raw response for this message in the worker trace.')
        self.import_raw_message(account,message_id,attachment_id,found)

    def save(self,account,message_id,attachment_id,category='inbox',issuer='',document_type='document',reference='',document_date=None):
        row=self.attachment(account,message_id,attachment_id)
        if category not in CATEGORIES: raise ValueError('Unknown document category.')
        if not row['sha256']: raise ValueError('Original bytes are unavailable; metadata is not a downloaded file.')
        with self.archive.db() as db:
            obj=db.execute('SELECT * FROM objects WHERE sha256=?',(row['sha256'],)).fetchone()
            message_row=db.execute('SELECT path FROM messages WHERE account=? AND id=?',(account,message_id)).fetchone()
        if not obj or not message_row: raise ValueError('Attachment lacks its original object or parent message.')
        original=(self.archive.root/obj['path']).resolve()
        message_path=(self.archive.root/message_row['path']).resolve()
        if not original.is_relative_to(self.archive.root) or not message_path.is_relative_to(self.archive.root):
            raise ValueError('Archive path escapes its root.')
        content=original.read_bytes();digest=hashlib.sha256(content).hexdigest()
        if digest!=row['sha256'] or len(content)!=obj['size']: raise ValueError('Original failed checksum verification.')
        target_dir=(self.vault/category).resolve()
        if not target_dir.is_relative_to(self.vault): raise ValueError('Category path escapes the document vault.')
        if document_date:
            issued=date.fromisoformat(document_date).isoformat();date_basis='confirmed_document_date'
        else:
            message=normalize(json.loads(message_path.read_text(encoding='utf-8')))
            if not message['sent']: raise ValueError('Document and source mail date are unknown; provide a confirmed --date.')
            issued=message['sent'][:10];date_basis='source_mail_date_fallback'
        suffix=Path(row['name']).suffix.casefold()
        if not re.fullmatch(r'\.[a-z0-9]{1,12}',suffix): suffix='.bin'
        pieces=[issued,slug(issuer,'unknown-issuer'),slug(document_type,'document')]
        if reference: pieces.append(slug(reference,'reference'))
        pieces.append(digest[:16])
        target=target_dir/('__'.join(pieces)+suffix)
        key=(account,message_id,attachment_id,category,digest)
        with self.archive.db() as db:
            previous=db.execute('SELECT path,provenance FROM document_copies WHERE account=? AND message_id=? AND attachment_id=? AND category=? AND sha256=?',key).fetchone()
            if previous:
                target=Path(previous['path']).resolve()
                if not target.is_relative_to(self.vault): raise ValueError('Previously filed path is outside this vault.')
                provenance=json.loads(previous['provenance'])
            else:
                provenance={**json.loads(row['source']),'account':account,'message_id':message_id,
                    'attachment_id':attachment_id,'original_name':row['name'],'sha256':digest,'mime':row['mime'],
                    'category':category,'document_date':issued,'date_basis':date_basis,'issuer':issuer,
                    'document_type':document_type,'reference':reference,'original_path':str(original),'path':str(target)}
            target.parent.mkdir(parents=True,exist_ok=True)
            try:
                with target.open('xb') as stream: stream.write(content)
            except FileExistsError:
                if hashlib.sha256(target.read_bytes()).hexdigest()!=digest: raise ValueError('Existing vault file has different bytes; it was not overwritten.')
            db.execute('INSERT OR IGNORE INTO document_copies VALUES(?,?,?,?,?,?,?)',(*key,str(target),json.dumps(provenance,ensure_ascii=False)))
            db.execute('UPDATE attachments SET category=? WHERE account=? AND message_id=? AND id=?',(category,account,message_id,attachment_id))
        return {'saved':True,'path':str(target),'original_path':str(original),'sha256':digest,'provenance':provenance}
