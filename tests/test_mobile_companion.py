import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from personal_assistant.groceries.mobile import Devices
from personal_assistant.relay.api import create_app


class MobileTests(unittest.TestCase):
    def test_pairing_one_use_expiry_and_revocation(self):
        with tempfile.TemporaryDirectory() as d:
            now=[1000];store=Devices(Path(d)/'phones.sqlite3',clock=lambda:now[0])
            first=store.pairing();phone=store.exchange(first['code'],'Phone')
            self.assertEqual(store.authenticate(phone['token']),phone['id'])
            with self.assertRaises(ValueError):store.exchange(first['code'],'Phone')
            expired=store.pairing();now[0]+=601
            with self.assertRaises(ValueError):store.exchange(expired['code'],'Phone')
            store.revoke(phone['id'])
            with self.assertRaises(ValueError):store.authenticate(phone['token'])
            self.assertNotIn(phone['token'],Path(d,'phones.sqlite3').read_bytes().decode('latin1'))

    def test_alarm_retries_and_expiry_do_not_claim_clock_success(self):
        with tempfile.TemporaryDirectory() as d:
            now=[1000];store=Devices(Path(d)/'phones.sqlite3',clock=lambda:now[0])
            p=store.exchange(store.pairing()['code'],'Phone');body={'hour':7,'minute':30,'type':'alarm','label':'Wake'}
            self.assertTrue(store.enqueue('alarm-request-1',p['id'],body)[1])
            self.assertFalse(store.enqueue('alarm-request-1',p['id'],body)[1])
            with self.assertRaises(ValueError):store.enqueue('alarm-request-1',p['id'],{**body,'hour':8})
            receipt=store.receipt(p['id'],'alarm-request-1','delegated')
            self.assertFalse(receipt['clock_registration_verified']);self.assertEqual(store.pending(p['id']),[])
            store.enqueue('alarm-request-2',p['id'],body);now[0]+=601
            self.assertEqual(store.pending(p['id']),[])
            with self.assertRaises(ValueError):store.receipt(p['id'],'alarm-request-2','delegated')

    def test_phone_scoped_token_cannot_queue_agents_pair_devices_or_read_other_phone_actions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);owner='o'*40
            app=create_app(root/'queue.sqlite3',owner,'w'*40,groceries={'path':root/'groceries.sqlite3','internal_token':'g'*40,
                'ha_url':'http://homeassistant:8123','assets':root,'user_verifier':lambda token: None if token==owner else (_ for _ in ()).throw(OSError())})
            client=TestClient(app);auth={'Authorization':'Bearer '+owner}
            def pair():
                code=client.post('/groceries/v1/mobile/pairing',headers=auth).json()['code']
                return client.post('/groceries/v1/mobile/exchange',json={'code':code}).json()
            first=pair();second=pair();device={'Authorization':'Bearer '+first['token']}
            self.assertEqual(client.get('/groceries/v1/mobile/list',headers=device).status_code,200)
            self.assertEqual(client.get('/groceries/v1/list',headers=device).status_code,401)
            self.assertEqual(client.post('/groceries/v1/mobile/pairing',headers=device).status_code,401)
            self.assertEqual(client.post('/v1/agent/prompts',headers=device,json={'id':'test-request','prompt':'Hello'}).status_code,401)
            self.assertEqual(client.post('/groceries/v1/mobile/mutations',headers=device,json={'id':'shopping-request','operation':'add','items':[{'name':'Flour'}]}).status_code,200)
            result=client.post('/groceries/v1/mobile/alarms',headers=auth,json={'id':'phone-alarm-01','phone':second['id'],'hour':7,'minute':30}).json()
            self.assertFalse(result['clock_registration_verified'])
            self.assertEqual(client.get('/groceries/v1/mobile/actions',headers=device).json(),[])
            self.assertEqual(client.post('/groceries/v1/mobile/actions/phone-alarm-01/receipt',headers=device,json={'state':'delegated'}).status_code,422)
