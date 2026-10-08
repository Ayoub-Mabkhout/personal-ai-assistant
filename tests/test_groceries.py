import tempfile
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from personal_assistant.groceries.store import Groceries, Conflict, split_items
from personal_assistant.relay.api import create_app


class GroceryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.store=Groceries(self.root/'groceries.sqlite3')
        self.body={'id':'request-1234','operation':'add','items':[{'name':'bananas'},{'name':'sparkling water'}]}

    def tearDown(self):
        self.temp.cleanup()

    def test_concurrent_retry_preserves_exactly_two_items(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.store.mutate(self.body),range(12)))
        self.assertEqual(len(self.store.snapshot()['items']),2)
        self.assertTrue(all(result==results[0] for result in results))
        with self.assertRaises(Conflict):
            self.store.mutate({**self.body,'items':[{'name':'milk'}]})

    def test_offline_stale_completion_cannot_overwrite_newer_change(self):
        item=self.store.mutate(self.body)['added_ids'][0]
        self.store.mutate({'id':'complete-1','operation':'complete','target':item,'version':1,'complete':True})
        with self.assertRaises(Conflict):
            self.store.mutate({'id':'complete-2','operation':'complete','target':item,'version':1,'complete':False})
        self.assertEqual(next(row for row in self.store.snapshot()['items'] if row['id']==item)['complete'],1)

    def test_failed_multi_item_add_rolls_back_and_can_be_fixed(self):
        with self.assertRaises(ValueError):
            self.store.mutate({**self.body,'items':[{'name':'milk'},{'name':'   '}]})
        self.assertEqual(self.store.snapshot()['items'],[])
        self.store.mutate(self.body)
        self.assertEqual(len(self.store.snapshot()['items']),2)

    def test_recipe_ingredients_are_copied_separately_and_retries_are_safe(self):
        recipe={'id':'recipe-123','title':'Breakfast','ingredients':[{'name':'banana','quantity':'2'},{'name':'oats','quantity':'100 g'}]}
        self.store.mutate({'id':'recipe-save','operation':'recipe_save','recipe':recipe})
        request={'id':'recipe-to-list','operation':'recipe_add','target':recipe['id']}
        self.store.mutate(request);self.store.mutate(request)
        self.assertEqual([x['quantity'] for x in self.store.snapshot()['items']],['2','100 g'])

    def test_voice_and_api_authentication(self):
        def verify(token):
            if token!='valid-ha-user':
                raise OSError('invalid')
        app=create_app(self.root/'queue.sqlite3','s'*48,'w'*48,groceries={
            'path':self.root/'groceries.sqlite3','internal_token':'g'*48,'ha_url':'http://unused',
            'assets':Path(__file__).resolve().parents[1]/'apps/groceries','user_verifier':verify})
        with TestClient(app) as client:
            self.assertEqual(client.get('/groceries/v1/list').status_code,401)
            self.assertEqual(client.get('/groceries/v1/list',headers={'Authorization':'Bearer invalid'}).status_code,401)
            response=client.post('/groceries/v1/voice',json={'id':'voice-123','text':'Hey Chat, add bananas and sparkling water to my shopping list'},headers={'Authorization':'Bearer valid-ha-user'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['names'],['bananas','sparkling water'])
            self.assertEqual(len(self.store.snapshot()['items']),2)
            self.assertEqual(client.get('/groceries/index-secret').status_code,404)
        self.assertEqual(split_items('mac and cheese, bananas'),['mac and cheese','bananas'])
