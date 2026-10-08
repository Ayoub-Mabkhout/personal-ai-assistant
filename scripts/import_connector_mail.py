"""Import connector message metadata and returned attachment downloads into the vault.

Input is a protected JSON file containing account, messages and downloads. This
does not reuse connector sign-in tokens for background Gmail/Graph access.
"""
import argparse
import json
from pathlib import Path
import urllib.parse
import urllib.request
from personal_assistant.connectors.mail import Archive


def import_batch(path, directory):
    body=json.loads(Path(path).read_text(encoding='utf-8'))
    archive=Archive(directory)
    account=body['account']
    for message in body.get('messages',[]):
        archive.save_message(account,message)
    downloaded=0
    failures=[]
    for item in body.get('downloads',[]):
        url=item['url']
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.oaiusercontent.com') or parsed.username:
            raise ValueError('Use only the connector-returned HTTPS attachment download.')
        try:
            with urllib.request.urlopen(url,timeout=60) as response:
                final=urllib.parse.urlsplit(response.url)
                if final.hostname!=parsed.hostname:
                    raise ValueError('Attachment download redirected to another host.')
                content=response.read(40*1024*1024+1)
            if len(content)>40*1024*1024 or len(content)!=item['size']:
                raise ValueError('Attachment size did not match connector metadata.')
        except (OSError,ValueError) as error:
            failures.append({'message_id':item['message_id'],'status':getattr(error,'code',None),'error':type(error).__name__})
            archive.attachment(account,item['message_id'],item['attachment_id'],item['name'],item['mime'],None,
                {'provider':'gmail-connector','download_failed':True})
            continue
        archive.attachment(account,item['message_id'],item['attachment_id'],item['name'],item['mime'],content,
            {'provider':'gmail-connector','message_id':item['message_id'],'retrieved_at':body['retrieved_at']})
        downloaded+=1
    for item in body.get('metadata',[]):
        with archive.db() as db:
            existing=db.execute('SELECT status FROM attachments WHERE account=? AND message_id=? AND id=?',
                (account,item['message_id'],item['attachment_id'])).fetchone()
        if not existing:
            archive.attachment(account,item['message_id'],item['attachment_id'],item['name'],item['mime'],None,
                {'provider':'gmail-connector','read_attachment_supported':item.get('supported',False)})
    return {'messages_imported':len(body.get('messages',[])),'attachments_downloaded':downloaded,'download_failures':failures,'verification':archive.verify()}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--archive',type=Path,default=Path.home()/'.personal-assistant/mail')
    args=parser.parse_args()
    print(json.dumps(import_batch(args.input,args.archive),indent=2))
