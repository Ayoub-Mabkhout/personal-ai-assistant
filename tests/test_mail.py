import base64
from pathlib import Path
import tempfile
import unittest
from personal_assistant.connectors.mail import Archive,GmailCrawler,OutlookCrawler,MailHTTP


class MailTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.archive=Archive(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_nested_gmail_parts_duplicate_content_and_safe_names(self):
        content=base64.urlsafe_b64encode(b'document bytes').decode().rstrip('=')
        class Fake:
            def get(_,url,binary=False):
                if '/messages?' in url:
                    return {'messages':[{'id':'m1'}]}
                return {'id':'m1','payload':{'parts':[{'parts':[
                    {'partId':'1','filename':'../../contract.pdf','mimeType':'application/pdf','body':{'data':content}},
                    {'partId':'2','filename':'copy.pdf','mimeType':'application/pdf','body':{'data':content}}]}]}}
        crawler=GmailCrawler(Fake(),self.archive,'gmail:one')
        self.assertEqual(crawler.scan()['messages_archived_this_run'],1)
        self.assertEqual(crawler.scan()['messages_archived_this_run'],0)
        with self.archive.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM objects').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attachments').fetchone()[0],2)
            paths=[row[0] for row in db.execute('SELECT path FROM objects')]
        self.assertTrue(all('..' not in Path(path).parts for path in paths))

    def test_graph_inline_files_and_linked_references_are_recorded(self):
        class Fake:
            def get(_,url,binary=False):
                if '/attachments' in url:
                    return {'value':[{'id':'a1','@odata.type':'#microsoft.graph.fileAttachment','name':'inline.pdf',
                        'contentType':'application/pdf','contentBytes':base64.b64encode(b'pdf').decode()},
                        {'id':'a2','@odata.type':'#microsoft.graph.referenceAttachment','name':'cloud contract'}]}
                return {'value':[{'id':'immutable-1','hasAttachments':False,'subject':'Test'}]}
        result=OutlookCrawler(Fake(),self.archive,'outlook:one').scan()
        self.assertTrue(result['full_scan_complete'])
        with self.archive.db() as db:
            statuses=[row[0] for row in db.execute('SELECT status FROM attachments ORDER BY id')]
        self.assertEqual(statuses,['archived','linked_requires_access'])

    def test_provider_escape_rejected_before_token_is_read(self):
        class Tokens:
            def token(_):
                raise AssertionError('Credential must not be read for an external URL')
        with self.assertRaises(ValueError):
            MailHTTP(Tokens(),'outlook').get('https://evil.example/next-page')

    def test_failed_page_resume_preserves_originals(self):
        class Fake:
            fail=True
            def get(self,url,binary=False):
                if 'pageToken=' in url:
                    if self.fail:
                        raise OSError('Simulated outage')
                    return {'messages':[{'id':'m2'}]}
                if '/messages?' in url:
                    return {'messages':[{'id':'m1'}],'nextPageToken':'page2'}
                return {'id':url.split('/messages/')[1].split('?')[0],'payload':{}}
        fake=Fake()
        crawler=GmailCrawler(fake,self.archive,'gmail:one')
        with self.assertRaises(OSError):
            crawler.scan()
        fake.fail=False
        self.assertEqual(crawler.scan()['messages_archived_this_run'],1)
        with self.archive.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM messages WHERE complete=1').fetchone()[0],2)

    def test_missing_attachment_data_does_not_complete_message(self):
        class Fake:
            def get(_,url,binary=False):
                if '/messages?' in url:
                    return {'messages':[{'id':'m1'}]}
                return {'id':'m1','payload':{'filename':'contract.pdf','body':{'size':50}}}
        with self.assertRaises(ValueError):
            GmailCrawler(Fake(),self.archive,'gmail:one').scan()
        self.assertFalse(self.archive.complete('gmail:one','m1'))

    def test_checksum_verification_detects_changed_bytes(self):
        self.archive.attachment('gmail:one','m1','a1','doc.pdf','application/pdf',b'original',{})
        self.assertTrue(self.archive.verify()['ok'])
        with self.archive.db() as db:
            path=self.archive.root/db.execute('SELECT path FROM objects').fetchone()[0]
        path.write_bytes(b'changed!')
        self.assertFalse(self.archive.verify()['ok'])


if __name__ == '__main__':
    unittest.main()
