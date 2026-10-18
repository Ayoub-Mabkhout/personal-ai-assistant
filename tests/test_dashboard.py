import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import personal_assistant.dashboard as dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'private/profile').mkdir(parents=True)
        (self.root/'runtime').mkdir()
        (self.root/'apps/dashboard').mkdir(parents=True)
        (self.root/'apps/dashboard/index.html').write_text("<html><script>const token='__DASHBOARD_TOKEN__';</script></html>")
        (self.root/'private/profile/topic.md').write_text('# Test theme\n\nUser-provided sample.')
        self.manifest=self.root/'private/profile/manifest.json'
        self.manifest.write_text(json.dumps({'themes':[{'id':'topic','file':'topic.md'}]}))
        self.patch=patch.object(dashboard,'ROOT',self.root)
        self.patch.start()
        self.client=TestClient(dashboard.create_app({'runtime_dir':str(self.root/'runtime')}),base_url='http://127.0.0.1:8787')
        self.token=re.search(r"const token='(.+?)'",self.client.get('/').text)[1]
        self.headers={'X-Dashboard-Token':self.token}

    def tearDown(self):
        self.client.close()
        self.patch.stop()
        self.temp.cleanup()

    def test_private_api_requires_local_session_token(self):
        self.assertEqual(self.client.get('/api/profile').status_code,401)
        response=self.client.get('/api/profile',headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertIn('sample',response.json()['themes'][0]['content'])

    def test_money_endpoint_is_private_and_returns_empty_state_without_ledger(self):
        client,headers=self.second_client(banking_ledger=str(self.root/'banking/ledger.sqlite3'))
        self.assertEqual(client.get('/api/money').status_code,401)
        response=client.get('/api/money',headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['available'])
        self.assertEqual(response.json()['transactions'],[])

    def test_money_endpoint_reads_local_ledger_and_exposes_category_and_fixed_fields(self):
        from personal_assistant.banking.ledger import Ledger, summarise
        path=self.root/'banking/ledger.sqlite3'
        ledger=Ledger(path)
        ledger.link('bank','DE',{'session_id':'session','accounts':[{'uid':'account','account_id':{'iban':'DE00'},'currency':'EUR'}]})
        ledger.store('account',[
            {'entry_reference':'rent','status':'BOOK','credit_debit_indicator':'DBIT','booking_date':'2026-10-01','transaction_amount':{'amount':'500','currency':'EUR'},'creditor':{'name':'Landlord'}},
            {'entry_reference':'food','status':'BOOK','credit_debit_indicator':'DBIT','booking_date':'2026-10-02','transaction_amount':{'amount':'20','currency':'EUR'},'creditor':{'name':'Cafe'}},
        ],'2026-10-01')
        rows={row['counterparty']:row for row in ledger.transactions()}
        ledger.decide(rows['Landlord']['id'],'fixed_cost','Housing',False,[],'Recurring',1,None,'ai')
        ledger.decide(rows['Cafe']['id'],'expense','Eating out',True,[],'Meal',1,'Was this a work lunch?','ai')
        client,headers=self.second_client(banking_ledger=str(path))
        response=client.get('/api/money',headers=headers)
        self.assertEqual(response.status_code,200)
        value=response.json()
        self.assertTrue(value['available'])
        self.assertEqual(value['fixed_costs'],[{'name':'Housing','cents':50000}])
        self.assertEqual(value['fixed_cents'],50000)
        self.assertEqual(value['categories'],[{'name':'Eating out','cents':2000}])
        self.assertEqual(value['review'][0]['question'],'Was this a work lunch?')
        self.assertEqual(len(value['transactions']),2)
        self.assertEqual(value['fixed_cost_transactions'][0]['category'],'Housing')
        self.assertEqual(len(value['category_transactions']['Eating out']),1)
        self.assertIn('recurring_breakdown',value)
        self.assertEqual(value['free_cents'],value['allowance']['amount_cents'])

    def test_money_question_uses_authenticated_durable_ledger_queue(self):
        from personal_assistant.banking.ledger import Ledger
        path=self.root/'banking/ledger.sqlite3'
        client,headers=self.second_client(banking_ledger=str(path))
        self.assertEqual(client.post('/api/money/questions',json={'request_id':'question-123','text':'Explain my spending'}).status_code,401)
        response=client.post('/api/money/questions',json={'request_id':'question-123','text':'Explain my spending'},headers=headers)
        self.assertEqual(response.status_code,200)
        sequence=response.json()['sequence']
        ledger=Ledger(path)
        jobs=ledger.jobs('pending')
        self.assertEqual([(job['kind'],job['job_key']) for job in jobs],[('question','question-123')])
        self.assertEqual(json.loads(jobs[0]['payload']),{'text':'Explain my spending','transaction':None})
        self.assertEqual(client.get(f'/api/money/questions/{sequence}',headers=headers).json(),
                         {'sequence':sequence,'state':'pending','reply':None})
        with ledger.db() as db:
            db.execute('INSERT INTO audit_outputs VALUES(?,?,?)',(sequence,'Local auditor reply',ledger.clock()))
        self.assertEqual(client.get(f'/api/money/questions/{sequence}',headers=headers).json()['reply'],'Local auditor reply')

    def test_money_owner_answer_records_once_and_clears_review_question(self):
        from personal_assistant.banking.ledger import Ledger,summarise
        path=self.root/'banking/ledger.sqlite3';ledger=Ledger(path)
        ledger.link('bank','DE',{'session_id':'session','accounts':[{'uid':'account','account_id':{'iban':'DE00'},'currency':'EUR'}]})
        ledger.store('account',[{'entry_reference':'review','status':'BOOK','credit_debit_indicator':'DBIT','booking_date':'2026-10-02',
            'transaction_amount':{'amount':'22','currency':'EUR'},'creditor':{'name':'Merchant'}}],'2026-10-01')
        row=ledger.transactions()[0]
        ledger.decide(row['id'],'expense','Food',True,[],'Maybe a shared meal',1,'Was this a shared meal?','ai')
        client,headers=self.second_client(banking_ledger=str(path));payload={'request_id':'answer-123','transaction':row['id'],'choice':'reimbursement','note':'This was my share being reimbursed.'}
        self.assertEqual(client.post('/api/money/answers',json=payload).status_code,401)
        response=client.post('/api/money/answers',json=payload,headers=headers)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json(),{'recorded':True,'duplicate':False})
        self.assertEqual(client.post('/api/money/answers',json=payload,headers=headers).json(),{'recorded':True,'duplicate':True})
        self.assertEqual(client.post('/api/money/answers',json={**payload,'note':'A different answer'},headers=headers).status_code,409)
        decided=ledger.transactions(include_gone=True)[0]
        self.assertEqual((decided['kind'],decided['by'],decided['question']),('reimbursement','owner',None))
        self.assertIn('This was my share',decided['reasoning'])
        self.assertEqual(summarise(ledger)['review'],[])
        self.assertEqual(client.post('/api/money/answers',json={**payload,'request_id':'answer-456'},headers=headers).status_code,409)

    def test_money_allowance_modes_and_period_definition_persist_locally(self):
        path=self.root/'banking/ledger.sqlite3';client,headers=self.second_client(banking_ledger=str(path))
        self.assertEqual(client.get('/api/money/allowance').status_code,401)
        automatic={'mode':'auto','start_day':5,'definition':'Regular income less recurring costs.'}
        self.assertEqual(client.post('/api/money/allowance',json=automatic,headers=headers).json()['mode'],'auto')
        pinned={'mode':'pinned','amount_cents':175000,'start_day':5,'definition':'Owner-set monthly allowance.'}
        self.assertEqual(client.post('/api/money/allowance',json=pinned,headers=headers).json()['amount_cents'],175000)
        reopened,_=self.second_client(banking_ledger=str(path))
        self.assertEqual(reopened.get('/api/money/allowance',headers=_).json(),{**pinned,'currency':'EUR','period':'month'})
        self.assertEqual(client.post('/api/money/allowance',json={'mode':'pinned','start_day':1},headers=headers).status_code,422)

    def test_shipped_money_page_uses_dashboard_route_and_supported_navigation(self):
        source=(Path(__file__).resolve().parents[1]/'apps/dashboard/index.html').read_text(encoding='utf-8')
        self.assertIn("data-page=\"money\"",source)
        self.assertIn("shared('money')",source)
        self.assertIn("const PAGES=['today','money'",source)
        self.assertIn("const LOADERS={money:loadMoney",source)
        for selector in ('.money-map','.money-block.fixed','.money-ring','.money-question-card','.money-category-hero','.chart-area','.money-monogram'):
            self.assertIn(selector,source)
        money_source=source[source.index('/* local money dashboard */'):source.index('/* accounts */')]
        self.assertIn("api('money/questions'",money_source)
        self.assertIn("api('money/answers'",money_source)
        self.assertIn("api('money/allowance'",money_source)
        self.assertNotIn("api('agent-prompts'",money_source)

    def test_daylight_preferences_remain_private_and_source_is_generic(self):
        prefs=self.root/'runtime/companion-preferences.json'
        prefs.write_text(json.dumps({'daylight':{'latitude':35.0,'longitude':-20.0},'secret':'omit'}))
        self.assertEqual(self.client.get('/api/preferences').status_code,401)
        value=self.client.get('/api/preferences',headers=self.headers)
        self.assertEqual(value.json(),{'daylight':{'latitude':35.0,'longitude':-20.0}})
        prefs.unlink()
        self.assertEqual(self.client.get('/api/preferences',headers=self.headers).json(),{'daylight':None})

    def second_client(self,**settings):
        client=TestClient(dashboard.create_app({'runtime_dir':str(self.root/'runtime'),**settings}),base_url='http://127.0.0.1:8787')
        self.addCleanup(client.close)
        token=re.search(r"const token='(.+?)'",client.get('/').text)[1]
        return client,{'X-Dashboard-Token':token}

    def test_preferences_file_setting_accepts_absolute_and_home_paths(self):
        place={'daylight':{'latitude':-20.5,'longitude':130.25}}
        absolute=self.root/'elsewhere.json'
        absolute.write_text(json.dumps({'daylight':{'latitude':0.0,'longitude':0.0}}))
        client,headers=self.second_client(mobile_settings_file=str(absolute))
        self.assertEqual(client.get('/api/preferences',headers=headers).json(),{'daylight':{'latitude':0.0,'longitude':0.0}})

        home=self.root/'home'
        home.mkdir()
        (home/'sun.json').write_text(json.dumps(place))
        with patch.dict(os.environ,{'HOME':str(home),'USERPROFILE':str(home)}):
            client,headers=self.second_client(mobile_settings_file='~/sun.json')
            self.assertEqual(client.get('/api/preferences',headers=headers).json(),place)

    def test_relative_preferences_file_setting_follows_the_process_directory(self):
        place={'daylight':{'latitude':-20.5,'longitude':130.25}}
        (self.root/'runtime/companion-preferences.json').write_text(json.dumps({'daylight':{'latitude':1,'longitude':2}}))
        (self.root/'protected').mkdir()
        (self.root/'protected/sun.json').write_text(json.dumps(place))
        previous=os.getcwd()
        os.chdir(self.root)
        try:
            with TestClient(dashboard.create_app({'runtime_dir':'runtime','mobile_settings_file':'protected/sun.json'}),base_url='http://127.0.0.1:8787') as client:
                token=re.search(r"const token='(.+?)'",client.get('/').text)[1]
                self.assertEqual(client.get('/api/preferences',headers={'X-Dashboard-Token':token}).json(),place)
            with TestClient(dashboard.create_app({'runtime_dir':'runtime'}),base_url='http://127.0.0.1:8787') as client:
                token=re.search(r"const token='(.+?)'",client.get('/').text)[1]
                self.assertEqual(client.get('/api/preferences',headers={'X-Dashboard-Token':token}).json(),
                    {'daylight':{'latitude':1,'longitude':2}})
        finally:
            os.chdir(previous)

    def test_empty_preferences_file_setting_uses_the_runtime_default(self):
        place={'daylight':{'latitude':-20.5,'longitude':130.25}}
        (self.root/'runtime/companion-preferences.json').write_text(json.dumps(place))
        for setting in (None,''):
            with self.subTest(setting=setting):
                client,headers=self.second_client(mobile_settings_file=setting)
                response=client.get('/api/preferences',headers=headers)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json(),place)

    def test_unreadable_preferences_are_not_reported_as_not_configured(self):
        prefs=self.root/'runtime/companion-preferences.json'
        prefs.mkdir()
        with self.assertLogs(level='WARNING') as logged:
            response=self.client.get('/api/preferences',headers=self.headers)
        self.assertEqual(response.status_code,503)
        self.assertNotIn('daylight',response.json())
        self.assertEqual(len(logged.records),1)
        self.assertNotIn(str(self.root),logged.output[0])
        prefs.rmdir()
        prefs.write_text(json.dumps({'daylight':{'latitude':-20.5,'longitude':130.25}}))
        self.assertEqual(self.client.get('/api/preferences',headers=self.headers).json(),
            {'daylight':{'latitude':-20.5,'longitude':130.25}})

    def test_dns_rebinding_host_rejected(self):
        self.assertEqual(self.client.get('/',headers={'Host':'attacker.example'}).status_code,400)

    def test_cross_origin_write_rejected(self):
        response=self.client.post('/api/pause',json={'paused':True},headers={**self.headers,'Origin':'https://attacker.example'})
        self.assertEqual(response.status_code,403)
        self.assertFalse((self.root/'runtime/pause.flag').exists())

    def test_pause_resume_changes_only_worker_control_file(self):
        self.assertEqual(self.client.post('/api/pause',json={'paused':True},headers=self.headers).status_code,200)
        self.assertTrue((self.root/'runtime/pause.flag').exists())
        self.client.post('/api/pause',json={'paused':False},headers=self.headers)
        self.assertFalse((self.root/'runtime/pause.flag').exists())

    def test_manifest_cannot_read_outside_profile(self):
        (self.root/'private/secret.md').write_text('Must not be returned')
        self.manifest.write_text(json.dumps({'themes':[{'id':'escape','file':'../secret.md'}]}))
        response=self.client.get('/api/profile',headers=self.headers)
        self.assertEqual(response.status_code,500)
        self.assertNotIn('Must not be returned',response.text)

    def test_followups_are_private_source_qualified_and_manageable(self):
        from personal_assistant.connectors.mail import Archive
        from personal_assistant.mail_followups import Followups
        archive=self.root/'mail';db_path=archive/'followups.sqlite3'
        Archive(archive).save_message('owner@example.com',{'id':'deadline','thread_id':'thread','internal_date':'1791293609000',
            'payload':{'headers':[{'name':'From','value':'Sender <sender@example.com>'}],
            'mime_type':'text/plain','body':{'content':'Please reply by 15 October 2026.'}}})
        store=Followups(db_path,archive)
        record=store.record('owner@example.com',{'kind':'deadline','title':'Reply to sender','message_id':'deadline',
            'quote':'Please reply by 15 October 2026.','due_date':'2026-10-15','certainty':'tentative'})
        private_config=self.root/'mail-config.json'
        private_config.write_text(json.dumps({'archive':str(archive),'followups_db':str(db_path),'runtime':str(self.root/'maintenance')}))
        client=TestClient(dashboard.create_app({'runtime_dir':str(self.root/'runtime'),'mail_automation_config':str(private_config)}),base_url='http://127.0.0.1:8787')
        token=re.search(r"const token='(.+?)'",client.get('/').text)[1];headers={'X-Dashboard-Token':token}
        self.assertEqual(client.get('/api/followups').status_code,401)
        response=client.get('/api/followups',headers=headers)
        self.assertEqual(response.status_code,200)
        item=response.json()['items'][0]
        self.assertEqual(item['quote'],'Please reply by 15 October 2026.')
        self.assertNotIn('account',item)
        self.assertNotIn(str(archive),response.text)
        self.assertIn('pending',response.json()['coverage_note'])
        path='/api/followups/'+record['id']
        self.assertEqual(client.post(path,json={'state':'resolved'},headers={**headers,'Origin':'https://attacker.example'}).status_code,403)
        self.assertEqual(store.get(record['id'])['state'],'open')
        self.assertEqual(client.post(path,json={'state':'resolved'},headers=headers).json()['state'],'resolved')
        self.assertEqual(client.get('/api/followups',headers=headers).json()['items'],[])
        self.assertEqual(len(client.get('/api/followups?state=resolved',headers=headers).json()['items']),1)
        self.assertEqual(client.post('/api/followups/not-an-id',json={'state':'resolved'},headers=headers).status_code,404)
        self.assertEqual(client.post(path,json={'state':'invented'},headers=headers).status_code,422)
        client.close()


class ShippedDashboardPageTests(unittest.TestCase):
    def test_pages_receive_one_session_token_and_call_only_existing_routes(self):
        pages={'/':'index.html','/whatsapp':'whatsapp.html'}
        with tempfile.TemporaryDirectory() as raw, TestClient(dashboard.create_app({'runtime_dir':raw}),base_url='http://127.0.0.1:8787') as client:
            routes={route.path for route in client.app.routes}
            for path,name in pages.items():
                with self.subTest(path):
                    html=client.get(path).text
                    self.assertEqual(len(re.findall(r"const token='[A-Za-z0-9_-]{20,}'",html)),1)
                    self.assertNotIn('__DASHBOARD_TOKEN__',html)
                    source=(dashboard.ROOT/'apps/dashboard'/name).read_text(encoding='utf-8')
                    called={'/api/'+call.split('?')[0].rstrip('/') for call in re.findall(r"(?:\b(?:api|shared)\('|fetch\('/api/)([^']+)'",source)}
                    self.assertTrue(called)
                    for call in called:
                        self.assertTrue(any(route==call or route.startswith(call+'/{') for route in routes),call)


if __name__=='__main__':
    unittest.main()
