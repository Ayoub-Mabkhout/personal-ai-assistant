"""File a catalogued email attachment; use live authorized bytes when not archived."""
import argparse
import json
from pathlib import Path
from personal_assistant.mail_documents import MailDocuments,CATEGORIES

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--archive',type=Path,default=Path.home()/'.personal-assistant/mail')
parser.add_argument('--vault',type=Path,default=Path(__file__).resolve().parents[1]/'private/documents')
parser.add_argument('--policy',type=Path)
for key in ('account','message-id','attachment-id'): parser.add_argument('--'+key,required=True)
parser.add_argument('--category',choices=sorted(CATEGORIES),default='inbox')
parser.add_argument('--issuer',default='')
parser.add_argument('--type',dest='document_type',default='document')
parser.add_argument('--reference',default='')
parser.add_argument('--date')
parser.add_argument('--provider',choices=['gmail','outlook'])
parser.add_argument('--credentials',type=Path)
parser.add_argument('--original-file',type=Path,help='Actual original downloaded by the authorized live connector; never extracted preview text.')
parser.add_argument('--message-json',type=Path,help='Exact live parent MIME/Graph message JSON to catalogue before filing.')
parser.add_argument('--artifact-json',type=Path,help='Exact Gmail read_attachment structured result, including its signed original file_uri; store outside OneDrive.')
original_source=parser.add_mutually_exclusive_group()
original_source.add_argument('--raw-message-json',type=Path,help='Authorized Gmail read_email(format=raw) result; original MIME, not a preview.')
original_source.add_argument('--raw-trace',type=Path,help='This worker own events.jsonl containing its successful Gmail raw read; avoids copying base64.')
args=parser.parse_args()
files=MailDocuments(args.archive,args.vault,args.policy)
if args.message_json:
    message=json.loads(args.message_json.read_text(encoding='utf-8-sig'))
    if message.get('id')!=args.message_id: parser.error('--message-json does not match --message-id')
    files.catalog_message(args.account,message)
if args.artifact_json:
    if 'onedrive' in str(args.artifact_json.resolve()).casefold(): parser.error('Signed artifact metadata must stay outside OneDrive')
    files.import_artifact(args.account,args.message_id,args.attachment_id,json.loads(args.artifact_json.read_text(encoding='utf-8-sig')))
if args.raw_message_json:
    files.import_raw_message(args.account,args.message_id,args.attachment_id,json.loads(args.raw_message_json.read_text(encoding='utf-8-sig')))
if args.raw_trace: files.import_raw_trace(args.account,args.message_id,args.attachment_id,args.raw_trace)
if args.original_file: files.import_original(args.account,args.message_id,args.attachment_id,args.original_file)
row=files.attachment(args.account,args.message_id,args.attachment_id)
if not row['sha256'] and args.provider and args.credentials:
    files.fetch(args.account,args.message_id,args.attachment_id,args.provider,args.credentials)
print(json.dumps(files.save(args.account,args.message_id,args.attachment_id,args.category,args.issuer,
    args.document_type,args.reference,args.date),ensure_ascii=False,indent=2))
