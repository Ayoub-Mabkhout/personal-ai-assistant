"""Isolated display enrichment: no bank access and no live model calls."""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from personal_assistant.banking import service
from personal_assistant.banking.agent import audit
from personal_assistant.banking.ledger import Ledger, public, summarise


class MoneyEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'ledger.sqlite3'
        self.ledger = Ledger(self.path)
        self.ledger.link('Test Bank', 'DE', {'session_id': 'synthetic', 'accounts': [
            {'uid': 'test', 'account_id': {'iban': 'DE00SYNTHETIC'}, 'currency': 'EUR'}]})
        self.ledger.store('test', [{'entry_reference': key, 'transaction_amount': {'amount': '10', 'currency': 'EUR'},
            'credit_debit_indicator': 'DBIT', 'booking_date': '2026-09-12', 'status': 'BOOK',
            'creditor': {'name': name}, 'remittance_information': ['Original bank description']}
            for key, name in [('dm', 'DM DROGERIEMARKT 123'), ('unknown', 'Ambiguous shop')]], '2026-09-01')
        for key in ('dm', 'unknown'):
            self.ledger.decide('test:' + key, 'expense', 'Other', True, [], 'Owner decision', 1, '', 'owner')

    def tearDown(self):
        self.temp.cleanup()

    def annotation(self, identity='test:dm', brand='dm'):
        return {'id': identity, 'display_title': 'Bathroom supplies', 'merchant_name': 'dm',
                'merchant_brand_id': brand, 'annotation_note': 'Drugstore payment; individual items are unknown.',
                'tags': ['drugstore'], 'confidence': .95, 'evidence': 'Original counterparty explicitly says DM DROGERIEMARKT.'}

    def test_additive_migration_and_annotations_preserve_originals_and_totals(self):
        originals = {r['id']: dict(r) for r in self.ledger.transactions()}
        before = self.ledger.transactions()[0]
        totals = summarise(self.ledger, date(2026, 9, 18))
        with self.ledger.db() as db:
            db.execute('DROP TABLE transaction_annotations')
        reopened = Ledger(self.path)
        self.assertEqual(reopened.transactions()[0]['raw'], before['raw'])
        self.assertTrue(reopened.annotate('test:dm', self.annotation(), 'ai'))
        row = next(r for r in reopened.transactions() if r['id'] == 'test:dm')
        for key in ('raw', 'counterparty', 'description', 'amount_cents', 'day', 'category', 'by'):
            original = originals['test:dm']
            self.assertEqual(row[key], original[key])
        updated = summarise(reopened, date(2026, 9, 18))
        for key in ('spent_cents', 'remaining_cents', 'net_cents', 'categories'):
            self.assertEqual(totals[key], updated[key])
        self.assertEqual(public(row)['display_title'], 'Bathroom supplies')
        self.assertEqual(public(row)['tags'], ['drugstore'])
        self.assertEqual(public(row)['annotation_by'], 'ai')
        older = service.history(reopened, date(2026, 10, 1))[0]
        item = next(r for r in older['category_transactions']['Other'] if r['id'] == 'test:dm')
        self.assertEqual((item['display_title'], item['merchant_brand_id']), ('Bathroom supplies', 'dm'))
        self.assertEqual(item['counterparty'], 'DM DROGERIEMARKT 123')

    def test_owner_annotation_wins_over_ai_even_on_owner_decided_transaction(self):
        self.ledger.annotate('test:dm', self.annotation(), 'owner')
        replacement = self.annotation() | {'display_title': 'AI replacement'}
        self.assertFalse(self.ledger.annotate('test:dm', replacement, 'ai'))
        row = next(r for r in self.ledger.transactions() if r['id'] == 'test:dm')
        self.assertEqual((row['display_title'], row['annotation_by'], row['by']), ('Bathroom supplies', 'owner', 'owner'))

    def test_unknown_or_unjustified_brand_is_rejected(self):
        for item in (self.annotation(brand='invented-brand'), self.annotation('test:unknown'),
                     self.annotation() | {'confidence': .5}):
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.ledger.annotate(item['id'], item, 'ai')
        unknown = self.annotation('test:unknown', None) | {'merchant_name': '', 'display_title': 'Unidentified payment'}
        self.assertTrue(self.ledger.annotate('test:unknown', unknown, 'ai'))

    def test_bounded_idempotent_job_resumes_same_session_without_accounting_changes(self):
        first = service.queue_enrichment(self.ledger, 'batch-one', ['test:dm'], 1)
        self.assertEqual(first, service.queue_enrichment(self.ledger, 'batch-one', ['test:dm'], 1))
        with self.assertRaises(ValueError):
            service.queue_enrichment(self.ledger, 'batch-one', ['test:unknown'], 1)
        with self.assertRaises(ValueError):
            service.queue_enrichment(self.ledger, 'too-large', limit=13)
        seen = []
        def fake(prompt, config, session, on_start):
            payload = json.loads(prompt)
            seen.append(session)
            self.assertEqual(payload['jobs'][0]['kind'], 'enrichment')
            self.assertEqual(payload['transactions_for_enrichment'][0]['counterparty'], 'DM DROGERIEMARKT 123')
            self.assertIn('dm', payload['brand_catalog'])
            return {'decisions': [], 'category_ops': [], 'insights': [], 'replies': [],
                    'enrichments': [self.annotation()]}, 'persistent-money-session'
        audit(self.ledger, {}, ask=fake, job_kind='enrichment', max_batches=1, batch_size=1)
        service.queue_enrichment(self.ledger, 'batch-two', ['test:dm'], 1)
        audit(self.ledger, {}, ask=fake, job_kind='enrichment', max_batches=1, batch_size=1)
        self.assertEqual(seen, [None, 'persistent-money-session'])
        self.assertEqual(next(r for r in self.ledger.transactions() if r['id'] == 'test:dm')['category'], 'Other')

    def test_enrichment_only_job_rejects_financial_mutation_or_missing_result(self):
        service.queue_enrichment(self.ledger, 'one', ['test:dm'], 1)
        token, jobs, session = self.ledger.claim_jobs(kind='enrichment')
        with self.assertRaisesRegex(ValueError, 'cannot change accounting'):
            self.ledger.finish_claim(token, jobs, session, [{'id': 'test:dm'}], [], [], enrichments=[self.annotation()])
        with self.assertRaisesRegex(ValueError, 'omitted a requested enrichment'):
            self.ledger.finish_claim(token, jobs, session, [], [], [])
        self.ledger.finish_claim(token, jobs, session, [], [], [], enrichments=[self.annotation()])

    def test_historical_annotations_keep_already_decoded_coverage_and_tags(self):
        self.ledger.decide('test:dm', 'expense', 'Groceries', True, [], 'Original', 1, '', 'owner',
                           coverage_months=['2026-09'])
        self.ledger.annotate('test:dm', self.annotation(), 'ai')
        history = service.history(self.ledger, date(2026, 10, 1))
        row = history[0]['category_transactions']['Groceries'][0]
        self.assertEqual(row['display_title'], 'Bathroom supplies')
        self.assertEqual(row['tags'], ['drugstore'])


if __name__ == '__main__':
    unittest.main()
