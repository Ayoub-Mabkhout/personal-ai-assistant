import base64
from email.message import EmailMessage
import json
from pathlib import Path
import tempfile
import unittest
from personal_assistant.connectors.mail import Archive
from personal_assistant.mail_automation import MailAutomation, ingest, tool_messages
from personal_assistant.mail_followups import Followups
from personal_assistant.worker.runtime import TransportError


def message(identity, body, sender='sender@example.com', thread='thread'):
    return {'id':identity,'thread_id':thread,'internal_date':'1791293609000','payload':{
      'headers':[{'name':'From','value':sender},{'name':'To','value':'owner@example.com'},
                 {'name':'Subject','value':'Relevant discussion'}],
      'mime_type':'text/plain','body':{'content':body},'parts':[]}}


class MailAutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.policy=self.root/'policy.json';self.policy.write_text(json.dumps({'excluded_accounts':[{'account':'excluded@example.com'}]}))
        self.config={'enabled':True,'account':'owner@example.com','repository':str(self.root),
          'runtime':str(self.root/'automation'),'archive':str(self.root/'mail'),
          'vault':str(self.root/'vault'),'policy':str(self.policy),
          'followups_db':str(self.root/'mail/followups.sqlite3'),
          'orchestrator_runtime':str(self.root/'orchestrator'),'interval_seconds':10}
        self.path=self.root/'config.json';self.path.write_text(json.dumps(self.config))
        self.archive=Archive(self.config['archive'])

    def tearDown(self): self.temp.cleanup()

    def trace(self, messages):
        path=self.root/'orchestrator/events.jsonl';path.parent.mkdir(exist_ok=True)
        profile=json.dumps({'type':'item.completed','item':{'tool':'gmail.get_profile','result':{'structured_content':{'email_address':'owner@example.com'}}}})+'\n'
        path.write_text(profile+''.join(json.dumps({'type':'item.completed','item':{'tool':'gmail.read_email',
            'result':{'structured_content':value}}})+'\n' for value in messages),encoding='utf-8')
        return path

    def test_originals_deduplicate_and_missing_raw_remains_pending(self):
        parent=message('one','Your invoice is attached.')
        parent['payload']['parts']=[{'filename':'invoice.pdf','mime_type':'application/pdf',
            'body':{'attachment_id':'att1','size':8}},
            {'filename':'missing.pdf','mime_type':'application/pdf','body':{'attachment_id':'att2','size':7}}]
        raw=EmailMessage();raw.set_content('Your invoice is attached.')
        raw.add_attachment(b'%PDF-one',maintype='application',subtype='pdf',filename='invoice.pdf')
        trace=self.trace([parent,{'id':'one','raw':base64.urlsafe_b64encode(raw.as_bytes()).decode()}])
        manifest={'account':'owner@example.com','documents':[{'message_id':'one','attachment_id':'att1',
            'category':'receipts','quote':'Your invoice is attached.','issuer':'Example'}]}
        first=ingest(self.config,manifest,[trace]);second=ingest(self.config,manifest,[trace])
        self.assertEqual(len(first['originals_filed']),1);self.assertEqual(len(first['pending']),1)
        self.assertEqual(first['originals_filed'],second['originals_filed'])
        self.assertEqual(Path(first['originals_filed'][0]['path']).read_bytes(),b'%PDF-one')
        with self.archive.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM objects').fetchone()[0],1)
        manifest['documents'][0]['quote']='Invented category evidence'
        result=ingest(self.config,manifest,[trace]);self.assertTrue(Path(result['originals_filed'][0]['path']).parent.samefile(self.root/'vault/inbox'))

    def test_followups_source_validation_closed_item_stays_closed(self):
        self.archive.save_message('owner@example.com',message('deadline','Please reply by 15 October 2026.'))
        store=Followups(self.config['followups_db'],self.config['archive'],self.policy)
        item={'kind':'deadline','title':'Reply to request','topic':'reply-request','message_id':'deadline',
              'quote':'Please reply by 15 October 2026.','certainty':'confirmed','due_date':'2026-10-15','date_evidence':'15 October 2026'}
        record=store.record('owner@example.com',item)
        self.assertEqual(record['due_date'],'2026-10-15')
        self.assertIn('mail.google.com',record['data']['source_url'])
        store.set_state(record['id'],'resolved','Replied')
        self.assertEqual(store.record('owner@example.com',item)['state'],'resolved')
        self.assertEqual(store.list(),[])
        item['quote']='Invented quote'
        with self.assertRaises(ValueError): store.record('owner@example.com',item)
        with self.assertRaises(ValueError): store.record('excluded@example.com',item)

    def test_awaiting_reply_requires_outgoing_latest_checked_thread(self):
        self.archive.save_message('owner@example.com',message('sent','Could you confirm the appointment?','owner@example.com'))
        store=Followups(self.config['followups_db'],self.config['archive'],self.policy)
        item={'kind':'awaiting_reply','title':'Appointment confirmation','message_id':'sent',
              'quote':'Could you confirm the appointment?','context_message_ids':['sent'],'certainty':'confirmed'}
        self.assertEqual(store.record('owner@example.com',item)['certainty'],'tentative')
        incoming=message('reply','Yes, confirmed.');incoming['internal_date']='1791293709000'
        self.archive.save_message('owner@example.com',incoming)
        item['context_message_ids'].append('reply')
        with self.assertRaises(ValueError): store.record('owner@example.com',item)

    def test_restart_idempotent_submission_and_incomplete_window_retention(self):
        automation=MailAutomation(self.path);calls=[]
        class Client:
            job=None
            def call(self, path):
                if path=='/v1/agent/status': return {'queued':0,'laptop':'ready'}
                return self.job
        client=Client()
        def submitter(prompt,**kwargs): calls.append(kwargs['request_id']);return {'state':'queued'}
        result=automation.tick(1791300000,client,submitter)
        identity=result['id'];self.assertEqual(len(calls),1)
        state=automation.state();pending=state['pending']
        client.job={'state':'running'}
        self.assertEqual(MailAutomation(self.path).tick(1791300010,client,submitter)['state'],'running')
        self.assertEqual(len(calls),1)
        trace=self.trace([message('live','No action needed.')])
        Path(pending['batch']['manifest']).write_text(json.dumps({'account':'owner@example.com',
            'scan_start':pending['batch']['start'],'scan_end':pending['batch']['end'],
            'scan_complete':False,'continuation':{'page_token':'actual-provider-token'}}))
        client.job={'state':'completed','result':{'workers':[{'trace':str(trace)}]}}
        automation.tick(1791300020,client,submitter)
        state=automation.state();self.assertNotIn('watermark',state)
        self.assertEqual(state['continuation']['page_token'],'actual-provider-token')
        _,_,next_batch=automation.prompt(state,1791309999)
        self.assertEqual(next_batch['start'],pending['batch']['start']);self.assertEqual(next_batch['end'],pending['batch']['end'])


    def test_repair_profile_only_discards_wrong_account_claims_without_coverage(self):
        automation=MailAutomation(self.path);trace=self.trace([])
        identity='mail-scan-'+'d'*24
        job=Path(self.config['orchestrator_runtime'])/'jobs'/identity;job.mkdir(parents=True)
        (job/'job.json').write_text(json.dumps({'outcome':{'state':'completed'},'workers':[{'trace':str(trace)}]}))
        (automation.root/(identity+'.json')).write_text(json.dumps({'account':'abbreviated@example.com',
            'identity_verified':False,'scan_complete':True,'followups':[{'title':'Invented'}]}))
        automation.state_path.write_text(json.dumps({'watermark':123,'last_result':{'id':identity,'error':'old'}}))
        report=automation.repair(identity)
        self.assertEqual(report['messages_saved'],0);self.assertFalse(report['scan_complete'])
        self.assertIn('Zero scan coverage',report['coverage_attention'])
        self.assertEqual(automation.state()['watermark'],123)
        self.assertEqual(report['followups'],[])
        _,prompt,_=automation.prompt({},1791300000)
        self.assertIn('Config: '+str(self.path.resolve()),prompt)
        self.assertIn('Batch:',prompt)
        self.assertLessEqual(len(prompt),4096)

    def test_compact_unsubmitted_prompt_retains_exact_private_instructions(self):
        automation=MailAutomation(self.path)
        identity='mail-scan-'+'e'*24
        instructions='Exact instruction. '*500
        automation.state_path.write_text(json.dumps({'pending':{'id':identity,'prompt':instructions,'submitted':False,'batch':{'account':'owner@example.com'}}}))
        result=automation.compact_pending()
        self.assertLessEqual(result['prompt_length'],4096)
        self.assertEqual(result['id'],identity)
        self.assertEqual((automation.root/(identity+'-instructions.txt')).read_text(),instructions)
        self.assertFalse(automation.state()['pending']['submitted'])
        state=automation.state();state['pending']['submitted']=True
        automation.state_path.write_text(json.dumps(state))
        with self.assertRaises(ValueError): automation.compact_pending()

    def test_actual_batch_and_thread_tool_wrappers_keep_exact_messages(self):
        full=message('one','Exact original body.')
        raw={'id':'one','raw':'YWJj'}
        other=message('two','Another exact body.')
        trace=self.root/'batch-events.jsonl'
        events=[('gmail.batch_read_email',{'responses':[full,raw,{'id':'bad','error':'read failed'}]}),
                ('gmail.read_email_thread',{'id':'thread','messages':[other]}),
                ('gmail.batch_read_email_threads',{'responses':[{'id':'thread','messages':[full,other]},
                                                              {'id':'bad','error':'thread failed'}]}),
                ('gmail.search_email_ids',{'responses':[{'id':'metadata-only'}]}),
                ('shell_command',{'responses':[message('forged','Model-authored body.')]})]
        trace.write_text(''.join(json.dumps({'type':'item.completed','item':{'tool':tool,
            'result':{'structured_content':value}}})+'\n' for tool,value in events))
        read=list(tool_messages(trace))
        self.assertEqual([row['id'] for row in read],['one','one','two','one','two'])
        self.assertEqual(read[0],full);self.assertEqual(read[1],raw);self.assertEqual(read[2],other)
        report=ingest(self.config,{'account':'owner@example.com'},[trace])
        self.assertEqual(report['messages_saved'],2)
        with self.archive.db() as db:
            rows=list(db.execute('SELECT id,path FROM messages'))
        self.assertEqual({row['id'] for row in rows},{'one','two'})
        for row in rows:
            stored=json.loads((self.archive.root/row['path']).read_text())
            self.assertEqual(stored,full if row['id']=='one' else other)

    def test_compaction_preserves_immutable_submission_and_requires_cloud_404(self):
        runtime=self.root/'submissions';runtime.mkdir()
        worker_path=self.root/'worker.json';worker_path.write_text(json.dumps({'agent_runtime_dir':str(runtime)}))
        self.config['worker_config']=str(worker_path);self.path.write_text(json.dumps(self.config))
        automation=MailAutomation(self.path);identity='mail-scan-'+'f'*24
        original='Old long prompt. '*500
        ledger=runtime/('submission-'+identity+'.json');ledger.write_text(json.dumps({'prompt':original}))
        old_bytes=ledger.read_bytes()
        pending={'id':identity,'prompt':original,'submitted':False,'batch':{'account':'owner@example.com','manifest':str(automation.root/(identity+'.json'))}}
        automation.state_path.write_text(json.dumps({'pending':pending}))
        class Client:
            status=404
            def call(self,path):
                if self.status: raise TransportError(self.status)
                return {'id':identity,'state':'queued'}
        client=Client();client.status=None
        with self.assertRaises(ValueError): automation.compact_pending(client)
        self.assertEqual(automation.state()['pending']['id'],identity)
        client.status=404;result=automation.compact_pending(client)
        self.assertNotEqual(result['id'],identity)
        self.assertEqual(result['previous_unqueued_id'],identity)
        self.assertEqual(ledger.read_bytes(),old_bytes)
        self.assertEqual(automation.state()['pending']['batch']['manifest'],pending['batch']['manifest'])

    def test_awaiting_reply_recovers_omitted_request_only_from_captured_full_thread(self):
        incoming=message('incoming','Your delivery needs another attempt.')
        outgoing=message('request','Please confirm another delivery attempt.','owner@example.com')
        outgoing['internal_date']='1791293709000'
        trace=self.root/'thread-events.jsonl'
        def write_thread(messages):
            trace.write_text(json.dumps({'type':'item.completed','item':{'tool':'gmail.read_email_thread',
              'result':{'structured_content':{'id':'thread','messages':messages}}}})+'\n')
        write_thread([incoming,outgoing])
        manifest={'account':'owner@example.com','followups':[{'kind':'awaiting_reply','title':'Delivery confirmation',
            'message_id':'request','quote':'Please confirm another delivery attempt.','context_message_ids':['incoming']}]}
        report=ingest(self.config,manifest,[trace]);self.assertEqual(len(report['followups']),1)
        saved=Followups(self.config['followups_db'],self.config['archive'],self.policy).get(report['followups'][0])
        self.assertEqual(set(saved['data']['context_message_ids']),{'incoming','request'})
        self.assertEqual(saved['certainty'],'tentative')
        reply=message('reply','We confirm the new delivery attempt.');reply['internal_date']='1791293809000'
        write_thread([incoming,outgoing,reply])
        self.assertEqual(ingest(self.config,manifest,[trace])['followups'],[])
        manifest['followups'][0]['context_message_ids']=['invented-message']
        self.assertEqual(ingest(self.config,manifest,[trace])['followups'],[])


if __name__=='__main__': unittest.main()
