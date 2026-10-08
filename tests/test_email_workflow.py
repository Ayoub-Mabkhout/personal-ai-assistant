import base64
from email.message import EmailMessage
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from personal_assistant.connectors.mail import Archive
from personal_assistant.email_index import MailIndex,normalize
from personal_assistant.mail_documents import MailDocuments
from personal_assistant.skill_repository import SkillRepository


def message(identity,thread='thread-a',subject='Contract for apartment',body='The handover is on Tuesday.',reply=''):
    return {'id':identity,'thread_id':thread,'internal_date':'1791293609000','payload':{
        'headers':[{'name':'Subject','value':subject},{'name':'From','value':'Landlord <landlord@example.com>'},
            {'name':'To','value':'user@example.com'},{'name':'Message-ID','value':'<'+identity+'@example.com>'},
            {'name':'References','value':reply}],
        'mime_type':'text/plain','body':{'content':body},'parts':None}}


class EmailWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.policy=self.root/'policy.json'
        self.policy.write_text(json.dumps({'excluded_accounts':[{'account':'excluded@example.com'}]}))
        self.archive=Archive(self.root/'mail');self.account='user@example.com'

    def tearDown(self): self.temp.cleanup()

    def test_search_thread_related_context_and_incremental_refresh(self):
        self.archive.save_message(self.account,message('first'))
        self.archive.save_message(self.account,message('second',body='The updated handover is Friday.'))
        self.archive.save_message(self.account,message('third','different-thread','Updated contract',reply='<first@example.com>'))
        self.archive.save_message('excluded@example.com',message('secret'))
        index=MailIndex(self.archive.root,self.policy)
        self.assertEqual(index.refresh(),3);self.assertEqual(index.refresh(),0)
        matches=index.search(subject='apartment',text='updated handover')
        self.assertEqual([row['id'] for row in matches],['second'])
        self.assertEqual(len(index.thread(self.account,'thread-a')),2)
        self.assertEqual(index.related(self.account,'first')[0]['id'],'third')
        self.assertFalse(index.coverage()['complete_mailbox'])
        with self.assertRaises(ValueError): index.read('excluded@example.com','secret')
        with self.assertRaises(ValueError): index.search(limit=10000)
        self.archive.save_message(self.account,message('second',body='Meeting cancelled.'))
        self.assertEqual(index.refresh(),1)
        self.assertEqual(index.search(subject='apartment',text='updated handover'),[])

    def test_html_fallback_and_null_mime_children(self):
        data=message('html');data['payload'].update(mime_type='text/html',body={'content':'<style>hidden</style><p>Visible &amp; relevant.</p>'})
        result=normalize(data)
        self.assertIn('Visible & relevant.',result['body']);self.assertNotIn('hidden',result['body'])

    def prepare_original(self):
        self.archive.save_message(self.account,message('original'))
        self.archive.attachment(self.account,'original','actual-provider-id','../../unsafe.pdf','application/pdf',b'%PDF-test-original',
            {'message_url':'https://example.com/source','provider':'gmail'})
        return MailDocuments(self.archive.root,self.root/'vault',self.policy)

    def test_filing_is_idempotent_and_preserves_source_and_previous_category(self):
        files=self.prepare_original()
        result=files.save(self.account,'original','actual-provider-id','contracts','The Issuer','rental-agreement','Ref/123')
        target=Path(result['path'])
        self.assertEqual(target.parent,self.root/'vault/contracts')
        self.assertEqual(target.read_bytes(),b'%PDF-test-original')
        self.assertTrue(target.name.startswith('2026-10-06__the-issuer__rental-agreement__ref-123__'))
        self.assertEqual(result['provenance']['date_basis'],'source_mail_date_fallback')
        self.assertEqual(result['provenance']['original_name'],'../../unsafe.pdf')
        again=files.save(self.account,'original','actual-provider-id','contracts','Different naming')
        self.assertEqual(again['path'],str(target))
        files.save(self.account,'original','actual-provider-id','housing','The Issuer')
        self.assertTrue(target.exists())
        with files.archive.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM document_copies').fetchone()[0],2)

    def test_missing_bytes_unsafe_category_and_overwrite_are_rejected(self):
        files=self.prepare_original()
        with self.assertRaises(ValueError): files.save(self.account,'original','actual-provider-id','../elsewhere')
        self.archive.attachment(self.account,'original','missing','metadata.pdf','application/pdf',None,{})
        with self.assertRaises(ValueError): files.save(self.account,'original','missing')
        result=files.save(self.account,'original','actual-provider-id')
        Path(result['path']).write_bytes(b'unrelated file')
        with self.assertRaises(ValueError): files.save(self.account,'original','actual-provider-id')
        self.assertEqual(Path(result['path']).read_bytes(),b'unrelated file')
        with self.assertRaises(ValueError): files.attachment('excluded@example.com','x','y')

    def test_live_parent_catalogue_and_original_import(self):
        data=message('live-parent')
        data['payload']['parts']=[{'filename':'document.pdf','mime_type':'application/pdf',
            'body':{'attachment_id':'live-attachment-id','size':18}}]
        files=MailDocuments(self.archive.root,self.root/'vault',self.policy)
        self.assertEqual(files.catalog_message(self.account,data),1)
        original=self.root/'download.pdf';original.write_bytes(b'%PDF-live-original')
        files.import_original(self.account,'live-parent','live-attachment-id',original)
        result=files.save(self.account,'live-parent','live-attachment-id',document_date='2026-09-01')
        self.assertEqual(result['provenance']['date_basis'],'confirmed_document_date')
        files.catalog_message(self.account,data)
        self.assertEqual(files.attachment(self.account,'live-parent','live-attachment-id')['sha256'],result['sha256'])
        original.write_bytes(b'different bytes')
        with self.assertRaises(ValueError): files.import_original(self.account,'live-parent','live-attachment-id',original)

    def test_authorized_raw_tool_trace_preserves_exact_attachment_bytes(self):
        files=self.prepare_original()
        self.archive.attachment(self.account,'original','raw-id','invoice.pdf','application/pdf',None,
            {'message_url':'https://example.com/source','expected_size':18})
        eml=EmailMessage();eml['Subject']='Invoice';eml.set_content('Attached invoice.')
        eml.add_attachment(b'%PDF-live-original',maintype='application',subtype='pdf',filename='invoice.pdf')
        response={'id':'original','raw':base64.urlsafe_b64encode(eml.as_bytes()).decode()}
        trace=self.root/'own-events.jsonl'
        trace.write_text(json.dumps({'type':'item.completed','item':{'tool':'gmail.read_email',
            'result':{'structured_content':response}}})+'\n',encoding='utf-8')
        files.import_raw_trace(self.account,'original','raw-id',trace)
        result=files.save(self.account,'original','raw-id','receipts')
        self.assertEqual(Path(result['path']).read_bytes(),b'%PDF-live-original')
        self.assertEqual(result['provenance']['acquisition'],'authorized_gmail_api_raw_message')
        self.assertTrue(Path(result['provenance']['raw_message_path']).is_file())
        with self.assertRaises(ValueError): files.import_raw_message(self.account,'wrong-message','raw-id',response)
        eml.add_attachment(b'%PDF-other-original',maintype='application',subtype='pdf',filename='invoice.pdf')
        response['raw']=base64.urlsafe_b64encode(eml.as_bytes()).decode()
        with self.assertRaises(ValueError): files.import_raw_message(self.account,'original','raw-id',response)

    def test_artifact_object_uses_original_url_checks_source_and_omits_signed_url_from_provenance(self):
        files=self.prepare_original();content=b'%PDF-test-original'
        artifact={'message_id':'original','attachment_id':'actual-provider-id','size_bytes':len(content),
            'file_uri':{'download_url':'https://files.oaiusercontent.com/raw?sig=private','file_id':'file-source-id'}}
        with patch('personal_assistant.mail_documents.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=BytesIO(content)
            files.import_artifact(self.account,'original','actual-provider-id',artifact)
            self.assertEqual(opener.return_value.open.call_args.args[0],artifact['file_uri']['download_url'])
        source=json.loads(files.attachment(self.account,'original','actual-provider-id')['source'])
        self.assertEqual(source['connector_file_id'],'file-source-id')
        self.assertNotIn('private',json.dumps(source))
        artifact['file_uri']['download_url']='https://untrusted.example/file'
        with self.assertRaises(ValueError): files.import_artifact(self.account,'original','actual-provider-id',artifact)
        artifact['message_id']='different'
        with self.assertRaises(ValueError): files.import_artifact(self.account,'original','actual-provider-id',artifact)

    def test_skill_catalog_works_outside_repository_and_rejects_unknown_skills(self):
        path=self.root/'skills/email/SKILL.md';path.parent.mkdir(parents=True)
        path.write_text('---\nname: email\ndescription: Search live email\n---\nRead the conversation.')
        skills=SkillRepository(self.root)
        self.assertEqual(skills.catalog()[0]['path'],str(path.resolve()))
        self.assertIn('Read the conversation.',skills.instructions(['email']))
        with self.assertRaises(ValueError): skills.instructions(['invented-skill'])


if __name__=='__main__': unittest.main()
