"""Query the source-qualified email snapshot without loading the entire inbox."""
import argparse
import json
from pathlib import Path
from personal_assistant.email_index import MailIndex

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('operation',choices=['search','read','thread','related'])
parser.add_argument('--archive',type=Path,default=Path.home()/'.personal-assistant/mail')
parser.add_argument('--policy',type=Path)
parser.add_argument('--account')
parser.add_argument('--message-id')
parser.add_argument('--thread-id')
for option in ('subject','sender','to','since','before','text'): parser.add_argument('--'+option)
parser.add_argument('--limit',type=int,default=20)
args=parser.parse_args()
index=MailIndex(args.archive,args.policy);changed=index.refresh()
if args.operation=='search':
    result=index.search(args.account,args.subject,args.sender,args.to,args.since,args.before,args.text,args.limit)
else:
    if not args.account: parser.error('--account is required for source-qualified reads')
    if args.operation=='thread':
        if not args.thread_id: parser.error('--thread-id is required')
        result=index.thread(args.account,args.thread_id)
    else:
        if not args.message_id: parser.error('--message-id is required')
        result=index.read(args.account,args.message_id) if args.operation=='read' else index.related(args.account,args.message_id,args.limit)
print(json.dumps({'coverage':index.coverage(),'index_messages_updated':changed,'results':result},ensure_ascii=False,indent=2))
