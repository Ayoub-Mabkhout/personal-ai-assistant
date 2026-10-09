import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from personal_assistant.groceries.store import Groceries
from personal_assistant.groceries.rewe import RetailerCheck, matches


class ReweChecks(unittest.TestCase):
    def test_spacing_case_and_conservative_synonyms(self):
        self.assertTrue(matches(' Sparkling   WATER ', 'Sprudelwasser'))
        self.assertTrue(matches('oatmilk', 'REWE Bio Haferdrink'))
        self.assertTrue(matches('BANANAS', 'Bio Bananen'))
        self.assertFalse(matches('gluten free bread', 'Bread'))
        self.assertFalse(matches('milk', 'Milchschokolade'))
        self.assertFalse(matches('still water', 'Sprudelwasser'))

    def test_persistent_interval_evidence_and_no_item_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Groceries(Path(temp)/'groceries.sqlite3')
            store.mutate({'id':'test-add','operation':'add','items':[{'name':'BANANAS'}]})
            now=time.time(); calls=[]
            def fetch(config, at):
                calls.append(at)
                return [{'name':'Bio Bananen','url':'https://www.rewe.de/market','state':'listed','valid_until':now+86400}]
            config={'interval_seconds':43200}; job=RetailerCheck(store,config,clock=lambda:now,fetch=fetch)
            self.assertEqual(job.run_once()['matched'],1)
            item=store.snapshot()['items'][0]
            self.assertEqual(item['retailer']['state'],'listed')
            self.assertFalse(item['retailer']['stock_verified'])
            self.assertEqual(item['version'],1)
            reboot=RetailerCheck(store,config,clock=lambda:now+10,fetch=fetch)
            self.assertFalse(reboot.run_once()); self.assertEqual(len(calls),1)
            store.mutate({'id':'test-edit','operation':'update','target':item['id'],'version':1,'name':'butter'})
            self.assertNotIn('retailer',store.snapshot()['items'][0])

    def test_blocked_check_never_guesses_availability(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Groceries(Path(temp)/'groceries.sqlite3')
            store.mutate({'id':'test-add','operation':'add','items':[{'name':'bananas'}]})
            def blocked(config,now): raise urllib.error.HTTPError('https://www.rewe.de',403,'blocked',{},None)
            job=RetailerCheck(store,{},fetch=blocked)
            self.assertEqual(job.run_once()['state'],'access_required')
            self.assertNotIn('retailer',store.snapshot()['items'][0])

    def test_available_tag_requires_explicit_stock_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Groceries(Path(temp)/'groceries.sqlite3')
            store.mutate({'id':'test-add','operation':'add','items':[{'name':'bananas'}]})
            now=time.time()
            job=RetailerCheck(store,{},clock=lambda:now,fetch=lambda c,n:[{'name':'Bananen','url':'https://www.rewe.de/market','state':'available','valid_until':now+86400}])
            job.run_once(); self.assertEqual(store.snapshot()['items'][0]['retailer']['state'],'listed')
