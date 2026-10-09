import json
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
