"""Live specialist tool contracts with an isolated ledger and fake logo provider."""
import io
import json
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

import test_money_enrichment as fixtures
from personal_assistant.banking.tools import MoneyTools, logo_catalog, serve


class MoneyToolTests(unittest.TestCase):
    annotation = fixtures.MoneyEnrichmentTests.annotation
    tearDown = fixtures.MoneyEnrichmentTests.tearDown
    def setUp(self):
        fixtures.MoneyEnrichmentTests.setUp(self)
        self.ledger.enqueue('question', 'display-edit', {'text': 'Enhance every imported transaction'})
        self.token, self.jobs, self.session = self.ledger.claim_jobs(kind='question')
        self.tools = MoneyTools(self.ledger, self.token)

    def test_search_pagination_and_live_edits_preserve_bank_and_decisions(self):
        page = self.tools.call('transactions_search', {'limit': 1, 'missing_only': True})
        self.assertEqual((page['total'], page['next_offset']), (2, 1))
        before = {r['id']:r for r in self.ledger.transactions()}
        result = self.tools.call('transaction_annotations_write', {'items': [self.annotation()]})
        self.assertEqual(result['saved'], 1)
        self.assertEqual(self.tools.call('enhancement_status', {})['missing'], 1)
        after = {r['id']:r for r in self.ledger.transactions()}
        for key in ('raw', 'amount_cents', 'day', 'category', 'counts', 'by'):
            self.assertEqual(before['test:dm'][key], after['test:dm'][key])

    def test_failed_batch_is_atomic_and_owner_annotation_wins(self):
        with self.assertRaises(ValueError):
            self.tools.call('transaction_annotations_write', {'items': [self.annotation(), self.annotation('test:unknown')]})
        self.assertEqual(self.tools.call('enhancement_status', {})['missing'], 2)
        self.ledger.annotate('test:dm', self.annotation(), 'owner')
        result = self.tools.call('transaction_annotations_write', {'items': [self.annotation() | {'display_title':'Replacement'}]})
        self.assertEqual(result['owner_annotations_preserved'], 1)

    def test_stale_lease_cannot_read_write_or_fetch(self):
        self.ledger.release_claim(self.token)
        for name,args in [('transactions_search',{}),('transaction_annotations_write',{'items':[self.annotation()]}),
                          ('merchant_logo_fetch',{'merchant_name':'dm','domain':'dm.de','evidence':'Known brand'})]:
            with self.assertRaisesRegex(ValueError,'lease'):
                self.tools.call(name,args)

    def test_logo_cached_with_provenance_and_bounded_image(self):
        png = b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',16,16)+b'\x08\x06\0\0\0'+b'\0'*4
        urls=[]
        self.tools.fetch=lambda url: urls.append(url) or png
        args={'merchant_name':'dm','domain':'dm.de','evidence':'Known merchant website'}
        self.assertFalse(self.tools.call('merchant_logo_fetch',args)['cached'])
        self.assertTrue(self.tools.call('merchant_logo_fetch',args)['cached'])
        self.assertEqual(len(urls),1)
        self.assertIn('dm',logo_catalog(self.ledger))
        self.assertNotIn('test:',urls[0])
        self.tools.fetch=lambda url: b'<html>not a logo</html>'
        with self.assertRaises(ValueError):
            self.tools.call('merchant_logo_fetch',{**args,'merchant_name':'Unknown','domain':'unknown.example'})
        with self.assertRaises(ValueError):
            self.tools.call('merchant_logo_fetch',{**args,'domain':'https://localhost/private'})

    def test_stdio_initialization_and_tool_call(self):
        source=io.StringIO('\n'.join(json.dumps(r) for r in [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'enhancement_status','arguments':{}}}]))
        target=io.StringIO();serve(self.tools,source,target)
        responses=[json.loads(line) for line in target.getvalue().splitlines()]
        self.assertEqual([r['id'] for r in responses],[1,2,3])
        self.assertEqual(len(responses[1]['result']['tools']),4)
        self.assertFalse(responses[2]['result']['isError'])

    def test_mcp_overrides_are_global_before_exec_resume(self):
        from personal_assistant.banking.agent import _run
        captured=[]
        class Process:
            pid=123;returncode=0
            def __init__(self,args,**kwargs):
                captured.append(args)
                Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(
                    {'decisions':[],'insights':[],'replies':[],'enrichments':[],'category_ops':[]}))
            def communicate(self,*args,**kwargs):return b'',b''
        with patch('personal_assistant.banking.agent.subprocess.Popen',Process):
            _run('Offline',{'codex':'codex','_money_tool_ledger':str(self.path),'_money_tool_lease':self.token},'same-session')
        args=captured[0]
        positions=[i for i,value in enumerate(args) if value.startswith('mcp_servers.money.')]
        self.assertTrue(positions)
        self.assertTrue(all(i<args.index('exec') for i in positions))
        self.assertNotIn('-c',args[args.index('exec')+1:])
        self.assertEqual(args[args.index('resume')+1],'same-session')

    def test_resumed_prompts_stay_small_and_large_sessions_are_retired(self):
        from datetime import date
        from personal_assistant.banking.agent import Prompt, ask, prompt_for
        full=json.loads(prompt_for(self.ledger,self.jobs,date(2026,10,18),{},''))
        resumed=json.loads(prompt_for(self.ledger,self.jobs,date(2026,10,18),{},'',resumed=True))
        self.assertIn('accounts',full);self.assertNotIn('accounts',resumed)
        self.assertTrue(all(isinstance(name,str) for name in resumed['category_catalog']))
        for row in full['recent_decided']:self.assertNotIn('reasoning',row);self.assertNotIn('annotation_evidence',row)
        answer={'decisions':[],'insights':[],'replies':[],'enrichments':[],'category_ops':[]}
        sent=[]
        class Process:
            pid=123
            def __init__(self,args,**kwargs):
                self.resumed='resume' in args;self.out=Path(args[args.index('--output-last-message')+1]);self.returncode=0
            def communicate(self,data,**kwargs):
                sent.append((self.resumed,data.decode()))
                if self.resumed:
                    self.returncode=1;return b'{"type":"turn.failed","error":{"message":"pre-sampling compact failed"}}',b''
                self.out.write_text(json.dumps(answer))
                return b'{"type":"thread.started","thread_id":"big"}\n{"type":"turn.completed","usage":{"input_tokens":150000}}',b''
            def wait(self,timeout=None):return 0
        with patch('personal_assistant.banking.agent.subprocess.Popen',Process),patch('personal_assistant.banking.agent.subprocess.run'):
            result=ask(Prompt('short','full'),{'codex':'codex','_money_tool_ledger':str(self.path),'_money_tool_lease':self.token},'old')
        # The rebuilt session receives the full prompt, and one that already read too much is not kept.
        self.assertEqual(sent,[(True,'short'),(False,'full')])
        self.assertEqual(result,(answer,None))

    def test_an_overgrown_or_hanging_session_is_rebuilt_from_the_ledger(self):
        import subprocess
        from personal_assistant.banking.agent import ask
        answer={'decisions':[],'insights':[],'replies':[],'enrichments':[],'category_ops':[]}
        for failure in ('compact','timeout'):
            sessions=[]
            class Process:
                pid=123
                def __init__(self,args,**kwargs):
                    self.resumed='resume' in args;sessions.append(args[args.index('resume')+1] if self.resumed else None)
                    self.out=Path(args[args.index('--output-last-message')+1]);self.returncode=0
                def communicate(self,*args,**kwargs):
                    if self.resumed and failure=='timeout':raise subprocess.TimeoutExpired('codex',1)
                    if self.resumed:
                        self.returncode=1
                        return b'{"type":"turn.failed","error":{"message":"Error running remote compact task: Bad Request"}}',b''
                    self.out.write_text(json.dumps(answer))
                    return b'{"type":"thread.started","thread_id":"fresh-session"}',b''
                def wait(self,timeout=None):return 0
            with patch('personal_assistant.banking.agent.subprocess.Popen',Process),patch('personal_assistant.banking.agent.subprocess.run'):
                result=ask('Offline',{'codex':'codex','_money_tool_ledger':str(self.path),'_money_tool_lease':self.token},'old-session')
            self.assertEqual(sessions,['old-session',None],failure)
            self.assertEqual(result,(answer,'fresh-session'),failure)


if __name__=='__main__':unittest.main()
