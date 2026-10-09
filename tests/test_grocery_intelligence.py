import tempfile
from pathlib import Path
import unittest
from personal_assistant.groceries.store import Groceries, Conflict
from personal_assistant.groceries.intelligence import ShoppingIntelligence
from personal_assistant.relay.voice import VoiceLedger


def action(op,name='',target='',quantity='',complete=False):
    return {'operation':op,'name':name,'target':target,'quantity':quantity,'complete':complete}


class GroceryIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.store=Groceries(root/'groceries.sqlite3');self.ledger=VoiceLedger(root/'voice.sqlite3')
        self.calls=[]
    def tearDown(self): self.temp.cleanup()
    def interpreter(self,plan):
        def interpret(identifier,text,items):self.calls.append(items);return plan(items)
        return ShoppingIntelligence(self.store,{},self.ledger,interpret)
    def test_mixed_multi_item_edits_are_atomic_and_replay_without_interpreting_again(self):
        self.store.mutate({'id':'seed','operation':'add','items':[{'name':'milk'},{'name':'eggs'}]})
        ai=self.interpreter(lambda items:{'intent':'grocery','question':'','changes':[action('delete',target=items[0]['id']),action('complete',target=items[1]['id'],complete=True),action('add','bananas',quantity='3'),action('add','sparkling water')]})
        result=ai.execute('mixed-request','Remove milk, mark eggs bought, add three bananas and sparkling water.')
        self.assertEqual(ai.execute('mixed-request','Remove milk, mark eggs bought, add three bananas and sparkling water.'),result)
        self.assertEqual(len(self.calls),1)
        rows=self.store.snapshot()['items'];self.assertEqual(len(rows),3)
        self.assertEqual(next(r for r in rows if r['name']=='eggs')['complete'],1)
        self.assertEqual(next(r for r in rows if r['name']=='bananas')['quantity'],'3')
    def test_invalid_target_rolls_back_all_changes(self):
        ai=self.interpreter(lambda items:{'intent':'grocery','question':'','changes':[action('add','banana'),action('delete',target='invented')]})
        with self.assertRaises(ValueError):ai.execute('bad-target','Add banana and remove that one.')
        self.assertEqual(self.store.snapshot()['items'],[])
    def test_concurrent_edit_rejects_whole_batch_without_partial_addition(self):
        item=self.store.mutate({'id':'seed','operation':'add','items':[{'name':'milk'}]})['added_ids'][0]
        def interpret(items):
            self.store.mutate({'id':'other-device','operation':'update','target':item,'version':1,'name':'oat milk'})
            return {'intent':'grocery','question':'','changes':[action('add','bananas'),action('delete',target=item)]}
        ai=self.interpreter(interpret)
        with self.assertRaises(Conflict):ai.execute('stale-request','Add bananas and remove milk.')
        self.assertEqual([r['name'] for r in self.store.snapshot()['items']],['oat milk'])
    def test_ambiguity_and_unrelated_requests_never_write(self):
        ai=self.interpreter(lambda items:{'intent':'clarify','question':'Which milk?','changes':[]})
        self.assertEqual(ai.execute('unclear','Remove that milk.')['status'],'needs_input')
        ai2=self.interpreter(lambda items:{'intent':'other','question':'','changes':[]})
        self.assertIsNone(ai2.execute('unrelated','Add a grocery receipt search feature.'))
        self.assertEqual(self.store.snapshot()['items'],[])
