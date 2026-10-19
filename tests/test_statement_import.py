import tempfile
import unittest
from datetime import date
from pathlib import Path

from personal_assistant.banking.ledger import Ledger
from personal_assistant.banking.statement_import import coalesce_provider_rows, import_rows
from personal_assistant.banking.service import history


def statement(key, day='2024-04-01', amount=-1200, merchant='Example shop'):
    return {'source_key':key,'day':day,'amount_cents':amount,'currency':'EUR',
            'counterparty':merchant,'description':merchant,'source_hash':'a'*64,
            'source':'private/statement.pdf','page':1}


def provider(key, day='2024-04-01', merchant='Example shop'):
    return {'entry_reference':key,'booking_date':day,'status':'BOOK',
            'transaction_amount':{'amount':'12.00','currency':'EUR'},
            'credit_debit_indicator':'DBIT','creditor':{'name':merchant}}


class StatementImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.ledger=Ledger(Path(self.temp.name)/'ledger.sqlite3')
        self.ledger.link('Example Bank','DE',{'session_id':'sample','accounts':[{'uid':'account','currency':'EUR'}]})

    def tearDown(self):self.temp.cleanup()

    def test_overlapping_feed_keeps_owner_decision_and_id(self):
        self.ledger.store('account',[provider('reference')],'2024-04-01')
        self.ledger.decide('account:reference','expense','Shopping',True,[],'owner correction',1,None,'owner')
        report=import_rows(self.ledger,'account',[statement('row')])
        self.assertEqual((report['inserted'],report['matched']),(0,1))
        report=import_rows(self.ledger,'account',[statement('row')])
        self.assertEqual(report['already_imported'],1)
        self.assertEqual(len(self.ledger.transactions()),1)
        self.assertEqual(self.ledger.transactions()[0]['by'],'owner')

    def test_later_feed_reuses_statement_row_without_double_spending(self):
        row=import_rows(self.ledger,'account',[statement('row')])['rows'][0]['id']
        self.ledger.decide(row,'expense','Shopping',True,[],'statement',.9,None,'ai')
        for _ in range(2):
            raws=coalesce_provider_rows(self.ledger,'account',[provider('bank-reference',day='2024-04-02')])
            self.ledger.store('account',raws,'2024-04-01')
        self.assertEqual(len(self.ledger.transactions()),1)
        self.assertEqual(self.ledger.transactions()[0]['id'],row)
        self.assertEqual(self.ledger.transactions()[0]['by'],'ai')

    def test_two_identical_real_payments_remain_two_and_unrelated_merchant_is_not_matched(self):
        self.ledger.store('account',[provider('one'),provider('two')],'2024-04-01')
        report=import_rows(self.ledger,'account',[statement('one'),statement('two')])
        self.assertEqual(report['matched'],2)
        self.assertEqual(len(self.ledger.transactions()),2)
        report=import_rows(self.ledger,'account',[statement('different',merchant='Unrelated airline')])
        self.assertEqual(report['inserted'],1)
        self.assertEqual(len(self.ledger.transactions()),3)

    def test_history_exposes_more_than_twelve_months(self):
        import_rows(self.ledger,'account',[statement('old')])
        months=history(self.ledger,date(2026,10,1))
        self.assertEqual(months[-1]['period']['start'],'2024-04-01')
        self.assertEqual(len(months),30)


if __name__=='__main__':unittest.main()
