from datetime import date
from contextlib import closing
import json
from pathlib import Path
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fastapi.testclient import TestClient

from personal_assistant.banking import service
from personal_assistant.banking.agent import audit
from personal_assistant.banking.ledger import Ledger, _process_alive, normalise, summarise
from personal_assistant.relay.api import create_app


def raw(reference, amount, debit, day, name='', status='BOOK', text='', iban=''):
    party = {'name': name}
    item = {'transaction_amount': {'amount': amount, 'currency': 'EUR'}, 'credit_debit_indicator': 'DBIT' if debit else 'CRDT',
            'status': status, 'booking_date': day, 'remittance_information': [text] if text else [],
            ('creditor' if debit else 'debtor'): party}
    if iban: item['creditor_account' if debit else 'debtor_account'] = {'iban': iban}
    if reference: item['entry_reference'] = reference
    return item


raw_tx = raw


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.temp.name) / 'ledger.sqlite3')
        self.ledger.link('Deutsche Bank', 'DE', {'session_id': 's1', 'access': {'valid_until': '2027-04-16'},
                         'accounts': [{'uid': 'db', 'account_id': {'iban': 'DE00SYNTH1'}, 'currency': 'EUR'}]})
        self.ledger.link('Revolut', 'DE', {'session_id': 's2', 'accounts': [{'uid': 'rv', 'account_id': {'iban': 'DE00SYNTH2'}, 'currency': 'EUR'}]})

    def tearDown(self):
        self.temp.cleanup()

    def test_signs_identity_and_dedupe(self):
        row = normalise('rv', raw('r1', '48.00', True, '2026-10-12', 'Trattoria'))
        self.assertEqual((row['id'], row['amount_cents'], row['counterparty']), ('rv:r1', -4800, 'Trattoria'))
        same = [raw('r1', '48.00', True, '2026-10-12', 'Trattoria')]
        self.assertEqual(self.ledger.store('rv', same + same, '2026-10-01'), 1)
        self.assertEqual(self.ledger.store('rv', same, '2026-10-01'), 0)
        # A reference-less pending payment gets a content identity and is marked gone once the bank stops listing it.
        pending = raw(None, '9.99', True, '2026-10-15', 'Shop', status='PDNG')
        self.ledger.store('rv', same + [pending], '2026-10-01')
        self.assertEqual(len(self.ledger.transactions()), 2)
        self.ledger.store('rv', same, '2026-10-01')
        self.assertEqual([r['id'] for r in self.ledger.transactions()], ['rv:r1'])

    def test_totals_follow_decisions_only(self):
        self.ledger.store('db', [raw('d1', '300', True, '2026-10-02', 'Self', text='Top-up'), raw('d2', '2940', False, '2026-10-01', 'Employer'),
                                 raw('d3', '900', True, '2026-10-03', 'Landlord')], '2026-10-01')
        self.ledger.store('rv', [raw('v1', '300', False, '2026-10-02', 'Self'), raw('v2', '48', True, '2026-10-12', 'Trattoria'),
                                 raw('v3', '24', False, '2026-10-14', 'Sara')], '2026-10-01')
        for identity, kind, counts, category in (('db:d1', 'internal_transfer', False, ''), ('rv:v1', 'internal_transfer', False, ''),
                ('db:d2', 'salary', False, ''), ('db:d3', 'fixed_cost', False, 'Rent'), ('rv:v2', 'expense', True, 'Eating out'),
                ('rv:v3', 'reimbursement', True, 'Eating out')):
            recurring = identity in ('db:d2', 'db:d3')
            monthly = {'db:d2': 294000, 'db:d3': 90000}.get(identity)
            self.ledger.decide(identity, kind, category, counts, [], 'test', 0.9, 'Sure?' if identity == 'rv:v3' else '', 'ai',
                               recurring=recurring, monthly_cents=monthly, series_key=identity if recurring else None)
        total = summarise(self.ledger, date(2026, 10, 18))
        self.assertEqual((total['spent_cents'], total['remaining_cents']), (2400, 201600))
        self.assertEqual((total['regular_income_cents'], total['recurring_costs_cents'], total['free_to_spend_cents']),
                         (294000, 90000, 204000))
        self.assertEqual(total['net_cents'], 294000 - 90000 - 4800 + 2400)
        self.assertEqual(total['period']['days_left'], 14)
        self.assertEqual(total['safe_per_day_cents'], 201600 // 14)
        self.assertEqual(total['categories'], [{'name': 'Rent', 'cents': 90000}, {'name': 'Eating out', 'cents': 2400}])
        self.assertEqual(total['fixed_costs'], [{'name': 'Rent', 'cents': 90000}])
        self.assertEqual(len(total['category_transactions']['Eating out']), 2)
        self.assertEqual([r['id'] for r in total['review']], ['rv:v3'])
        # The owner's word stands against a later agent revision.
        rows = {r['id']: r for r in self.ledger.transactions()}
        self.assertTrue(service.answer(self.ledger, rows['rv:v3'], 'confirm'))
        self.assertFalse(self.ledger.decide('rv:v3', 'income', '', False, [], 'x', 0.5, '', 'ai'))
        self.assertEqual(summarise(self.ledger, date(2026, 10, 18))['review'], [])

    def test_audit_applies_model_decisions_and_never_overrides_the_owner(self):
        self.ledger.store('rv', [raw('v1', '10', True, '2026-10-05', 'Cafe'), raw('v2', '5', True, '2026-10-06', 'Cafe')], '2026-10-01')
        seen = []

        def ask(prompt, config, session, on_start):
            seen.append(json.loads(prompt))
            return ({'decisions': [{'id': i, 'kind': 'expense', 'category': 'Eating out', 'counts': True, 'linked': [],
                                   'reasoning': 'Coffee.', 'confidence': 1.4, 'question': '', 'recurring': False,
                                   'monthly_cents': None, 'coverage_months': [], 'series_key': None}
                                  for i in ('rv:v1', 'rv:v2', 'rv:unknown')],
                    'insights': [{'kind': 'pace', 'text': 'On track.'}], 'replies': []}, 'session-1')
        decided, insights = audit(self.ledger, {}, date(2026, 10, 18), ask=ask)
        self.assertEqual(decided, 2)
        self.assertEqual(seen[0]['allowance']['mode'], 'auto')
        self.assertEqual({r['confidence'] for r in self.ledger.transactions()}, {1.0})
        self.assertEqual(self.ledger.setting('insights'), insights)
        self.assertEqual(audit(self.ledger, {}, ask=ask), (0, None))

    def test_coverage_offsets_and_manual_pin(self):
        self.ledger.store('db', [raw('wage', '2000', False, '2026-09-28', 'Employer'),
                                 raw('support', '1000', False, '2026-09-10', 'Family'),
                                 raw('rent', '800', True, '2026-10-03', 'Landlord'),
                                 raw('food', '60', True, '2026-10-04', 'Market')], '2026-09-01')
        self.ledger.decide('db:wage', 'salary', '', False, [], 'Regular wage', 1, '', 'ai',
                           recurring=True, monthly_cents=200000, coverage_months=['2026-09'], series_key='wage')
        self.ledger.decide('db:support', 'income', '', False, [], 'Two months of support', 1, '', 'ai',
                           recurring=True, monthly_cents=50000, coverage_months=['2026-08', '2026-09'], series_key='support')
        self.ledger.decide('db:rent', 'fixed_cost', 'Housing', False, [], 'Lease', 1, '', 'ai',
                           recurring=True, monthly_cents=80000, series_key='rent')
        self.ledger.decide('db:food', 'expense', 'Groceries', True, [], 'Food', 1, '', 'ai')
        self.assertTrue(self.ledger.add_adjustment('cash-1', '2026-10-05', 'cash_offset', 2000,
                                                   'Groceries', ['db:food'], 'Owner confirmed cash repayment', 'owner'))
        self.assertFalse(self.ledger.add_adjustment('cash-1', '2026-10-05', 'cash_offset', 2000,
                                                    'Groceries', ['db:food'], 'Owner confirmed cash repayment', 'owner'))
        summary = summarise(self.ledger, date(2026, 10, 18))
        self.assertEqual((summary['regular_income_cents'], summary['recurring_costs_cents'],
                          summary['free_to_spend_cents']), (250000, 80000, 170000))
        self.assertEqual((summary['spent_cents'], summary['remaining_cents']), (4000, 166000))
        self.assertEqual(summary['net_cents'], -86000)
        self.assertEqual(summary['payday_aware_net_cents'], 166000)
        self.assertEqual(summary['categories'][1], {'name': 'Groceries', 'cents': 4000})
        self.assertEqual(len(summary['category_transactions']['Groceries']), 2)
        self.assertEqual(len(self.ledger.transactions()), 4)
        self.ledger.set_setting('allowance', {'amount_cents': 120000, 'start_day': 1, 'period': 'month'})
        self.assertEqual(summarise(self.ledger, date(2026, 10, 18))['remaining_cents'], 116000)

    def test_queue_fence_replay_and_question_response(self):
        self.ledger.store('rv', [raw('one', '5', True, '2026-10-01', 'Cafe')], '2026-10-01')
        question = service.ask_question(self.ledger, 'request-1', 'Explain this month')
        first = self.ledger.claim_jobs()
        self.assertIsNone(self.ledger.claim_jobs())
        token, jobs, _ = first
        self.assertEqual([j['kind'] for j in jobs], ['transaction', 'question'])
        decision = {'id': 'rv:one', 'kind': 'expense', 'category': 'Eating out', 'counts': True,
                    'linked': [], 'reasoning': 'Cafe', 'confidence': 0.9, 'question': '',
                    'recurring': False, 'monthly_cents': None, 'coverage_months': [], 'series_key': None}
        self.ledger.finish_claim(token, jobs, 'session-1', [decision], [], [{'job_seq': question, 'text': 'One cafe payment.'}])
        self.assertEqual(self.ledger.audit_output(question), 'One cafe payment.')
        self.assertIsNone(self.ledger.claim_jobs())
        self.ledger.decide('rv:one', 'expense', 'Eating out', True, [], 'Owner correction', 1, '', 'owner')
        with self.assertRaises(RuntimeError):
            self.ledger.finish_claim(token, jobs, 'session-1', [decision], [], [])
        self.assertEqual(self.ledger.transactions()[0]['by'], 'owner')

    def test_expired_claim_cannot_replay_a_mutation(self):
        moment = [1000.0]
        self.ledger.clock = lambda: moment[0]
        self.ledger.store('rv', [raw('one', '5', True, '2026-10-01', 'Cafe')], '2026-10-01')
        old_token, old_jobs, _ = self.ledger.claim_jobs(lease_seconds=10)
        moment[0] += 11
        new_token, new_jobs, _ = self.ledger.claim_jobs(lease_seconds=10)
        self.assertNotEqual(old_token, new_token)
        decision = {'id': 'rv:one', 'kind': 'expense', 'category': 'Eating out', 'counts': True,
                    'linked': [], 'reasoning': 'Cafe', 'confidence': 1, 'question': '',
                    'recurring': False, 'monthly_cents': None, 'coverage_months': [], 'series_key': None}
        with self.assertRaises(RuntimeError):
            self.ledger.finish_claim(old_token, old_jobs, 'stale', [decision], [], [])
        self.ledger.finish_claim(new_token, new_jobs, 'current', [decision], [], [])
        self.assertEqual(self.ledger.transactions()[0]['kind'], 'expense')

    def test_expired_claim_waits_for_live_auditor_process(self):
        moment = [1000.0]
        self.ledger.clock = lambda: moment[0]
        self.ledger.store('rv', [raw('one', '5', True, '2026-10-01', 'Cafe')], '2026-10-01')
        token, _, _ = self.ledger.claim_jobs(lease_seconds=10)
        self.assertTrue(_process_alive(os.getpid()))
        self.ledger.set_claim_process(token, os.getpid())
        moment[0] += 11
        self.assertIsNone(self.ledger.claim_jobs())

    def test_publish_keeps_category_details_and_paginates_transactions_over_sixty(self):
        raws = [raw('fixed-%03d' % i, '12.34', True, '2026-10-%02d' % (1 + i % 18), 'Utility', text='Monthly bill')
                for i in range(63)]
        raws += [raw('food-%03d' % i, '8.50', True, '2026-10-%02d' % (1 + i % 18), 'Market', text='Groceries')
                 for i in range(12)]
        self.ledger.store('db', raws, '2026-10-01')
        for i in range(63):
            identity = 'db:fixed-%03d' % i
            self.ledger.decide(identity, 'fixed_cost', 'Utilities', False, [], 'Monthly bill', 0.95, '', 'ai')
        for i in range(12):
            identity = 'db:food-%03d' % i
            self.ledger.decide(identity, 'expense', 'Groceries', True, [], 'Food', 0.95, '', 'ai')

        class Relay:
            def __init__(self): self.payloads = []
            def call(self, path, payload, method=None): self.payloads.append(payload)

        relay = Relay()
        first = service.publish(relay, self.ledger, date(2026, 10, 18), page_size=30)
        self.assertEqual((len(first['transactions']), first['transactions_page']['returned']), (30, 30))
        self.assertTrue(first['transactions_page']['has_more'])
        self.assertEqual(len(first['category_transactions']['Utilities']), 63)
        self.assertEqual(len(first['category_transactions']['Groceries']), 12)
        self.assertEqual(len(first['fixed_cost_transactions']), 63)
        self.assertLess(len(json.dumps(first, ensure_ascii=False).encode('utf-8')), service.SUMMARY_LIMIT)
        all_ids = [row['id'] for row in first['transactions']]
        cursor = first['transactions_page']['next_cursor']
        while cursor:
            page = service.publish(relay, self.ledger, date(2026, 10, 18), transaction_cursor=cursor, page_size=30)
            all_ids.extend(row['id'] for row in page['transactions'])
            cursor = page['transactions_page']['next_cursor']
        self.assertEqual(len(all_ids), 75)
        self.assertEqual(len(set(all_ids)), 75)
        self.assertTrue(all('raw' not in row for row in first['fixed_cost_transactions']))

    def test_publish_rejects_oversized_complete_detail_without_slicing(self):
        self.ledger.store('db', [raw('large', '1', True, '2026-10-01', 'Shop', text='x' * service.SUMMARY_LIMIT)],
                          '2026-10-01')
        self.ledger.decide('db:large', 'expense', 'Other', True, [], 'Large test row', 1, '', 'ai')

        class Relay:
            def __init__(self): self.calls = 0
            def call(self, *args, **kwargs): self.calls += 1

        relay = Relay()
        with self.assertRaisesRegex(ValueError, 'Complete Money summary exceeds'):
            service.publish(relay, self.ledger, date(2026, 10, 18))
        self.assertEqual(relay.calls, 0)

    def test_legacy_owner_decision_survives_schema_migration(self):
        path = Path(self.temp.name) / 'legacy.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE decisions(id TEXT PRIMARY KEY,kind TEXT NOT NULL,category TEXT,counts INTEGER NOT NULL,'
                       "linked TEXT NOT NULL DEFAULT '[]',reasoning TEXT,confidence REAL,question TEXT,by TEXT NOT NULL,at REAL NOT NULL)")
            db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('owned', 'expense', 'Groceries', 1, '[]', 'Owner confirmed', 1, None, 'owner', 1.0))
        Ledger(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT kind,category,by FROM decisions WHERE id=?', ('owned',)).fetchone(),
                             ('expense', 'Groceries', 'owner'))
            self.assertIn('coverage_months', {r[1] for r in db.execute('PRAGMA table_info(decisions)')})


class IncomeTrackerTests(unittest.TestCase):
    def test_a_transfer_covering_two_months_fills_both_and_a_late_month_shows_missing(self):
        with tempfile.TemporaryDirectory() as raw:
            ledger = Ledger(Path(raw) / 'ledger.sqlite3')
            ledger.link('Main', 'DE', {'session_id': 's', 'accounts': [{'uid': 'm', 'currency': 'EUR'}]})
            ledger.store('m', [raw_tx('f1', '1000', False, '2026-09-10', 'Parent'), raw_tx('s1', '1200', False, '2026-09-28', 'Employer')], '2026-09-01')
            ledger.decide('m:f1', 'income', 'Family complement', False, [], 'x', 1.0, None, 'owner', recurring=True,
                          monthly_cents=50000, coverage_months=['2026-08', '2026-09'], series_key='income:family')
            ledger.decide('m:s1', 'salary', 'Salary', False, [], 'x', 1.0, None, 'owner', recurring=True,
                          monthly_cents=120000, coverage_months=['2026-09'], series_key='income:salary')
            total = summarise(ledger, date(2026, 10, 18))
            self.assertEqual(total['regular_income_cents'], 170000)
            family = next(s for s in total['income_tracker'] if s['key'] == 'income:family')
            self.assertEqual([(m['month'], m['received']) for m in family['months']],
                             [('2026-08', True), ('2026-09', True), ('2026-10', False)])


class ConsentProjectionTests(unittest.TestCase):
    def test_provider_timestamps_are_published_as_plain_dates_for_the_relay_reminder(self):
        with tempfile.TemporaryDirectory() as raw:
            ledger = Ledger(Path(raw) / 'ledger.sqlite3')
            ledger.link('Main', 'DE', {'session_id': 's', 'access': {'valid_until': '2027-04-16T15:55:46Z'}, 'accounts': []})
            self.assertEqual(summarise(ledger, date(2026, 10, 18))['banks'], [{'bank': 'Main', 'valid_until': '2027-04-16'}])


class CategoryCatalogueTests(unittest.TestCase):
    def test_auditor_curates_categories_but_never_the_owners(self):
        with tempfile.TemporaryDirectory() as raw:
            ledger = Ledger(Path(raw) / 'ledger.sqlite3')
            ledger.link('Main', 'DE', {'session_id': 's', 'accounts': [{'uid': 'm', 'currency': 'EUR'}]})
            ledger.store('m', [raw_tx('a', '5', True, '2026-10-02', 'Kiosk'), raw_tx('b', '9', True, '2026-10-03', 'Bakery')], '2026-10-01')
            ledger.decide('m:a', 'expense', 'Snacks', True, [], 'x', 0.9, None, 'ai')
            ledger.decide('m:b', 'expense', 'Bakery', True, [], 'x', 0.9, None, 'ai')
            ledger.apply_category_op({'op': 'create', 'name': 'Rent', 'group': 'fixed', 'emoji': 'R', 'budget_cents': 42260}, 'owner')
            ops = [{'op': 'create', 'name': 'Food on the go', 'emoji': 'F', 'group': 'elective', 'suggested_budget_cents': 6000},
                   {'op': 'merge', 'name': 'Snacks', 'into': 'Food on the go'},
                   {'op': 'update', 'name': 'Bakery', 'new_name': 'Bakeries'},
                   {'op': 'delete', 'name': 'Rent'},
                   {'op': 'delete', 'name': 'Food on the go'}]
            for op in ops:
                try:
                    ledger.apply_category_op(op, 'ai')
                except ValueError:
                    pass  # deleting a used category without a target is refused
            names = {c['name']: c for c in ledger.categories()}
            self.assertEqual(set(names), {'Food on the go', 'Bakeries', 'Rent'})
            self.assertEqual(names['Rent']['budget_cents'], 42260)
            self.assertIsNone(names['Food on the go']['budget_cents'])
            self.assertEqual({r['id']: r['category'] for r in ledger.transactions()}, {'m:a': 'Food on the go', 'm:b': 'Bakeries'})
            self.assertIn('category_catalog', summarise(ledger, date(2026, 10, 18)))


class RelayBankingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(root / 'queue.sqlite3', 's' * 40, 'w' * 40, groceries={'path': root / 'groceries.sqlite3',
                              'internal_token': 'g' * 40, 'assets': root})
        devices = self.app.state.mobile_events.devices
        self.mobile = {'Authorization': 'Bearer ' + devices.exchange(devices.pairing()['code'], 'Synthetic phone')['token']}
        self.owner = {'Authorization': 'Bearer ' + 's' * 40}
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_callback_is_announced_single_use_and_owner_only(self):
        state = 'S' * 32
        self.assertIn('Link expired', self.client.get('/v1/banking/callback', params={'state': state, 'code': 'c'}).text)
        self.assertEqual(self.client.post('/v1/banking/pending', json={'state': state}).status_code, 401)
        self.client.post('/v1/banking/pending', json={'state': state}, headers=self.owner)
        self.assertEqual(self.client.get('/v1/banking/pending/' + state, headers=self.owner).json(), {'status': 'waiting'})
        self.assertIn('Bank linked', self.client.get('/v1/banking/callback', params={'state': state, 'code': 'one-time'}).text)
        self.assertIn('Link expired', self.client.get('/v1/banking/callback', params={'state': state, 'code': 'forged'}).text)
        self.assertEqual(self.client.get('/v1/banking/pending/' + state, headers=self.owner).json(), {'status': 'returned', 'code': 'one-time'})
        self.assertEqual(self.client.get('/v1/banking/pending/' + state, headers=self.owner).status_code, 404)
        cancelled = 'C' * 32
        self.client.post('/v1/banking/pending', json={'state': cancelled}, headers=self.owner)
        self.assertIn('cancelled', self.client.get('/v1/banking/callback', params={'state': cancelled, 'error': 'access_denied'}).text)
        self.assertEqual(self.client.get('/v1/banking/pending/' + cancelled, headers=self.owner).json()['status'], 'error')

    def test_summary_and_answers_between_laptop_and_phone(self):
        self.assertEqual(self.client.get('/groceries/v1/mobile/money', headers=self.mobile).json()['summary'], None)
        self.assertEqual(self.client.put('/v1/banking/summary', json={'spent_cents': 1}, headers=self.mobile).status_code, 401)
        self.client.put('/v1/banking/summary', json={'spent_cents': 1}, headers=self.owner)
        self.assertEqual(self.client.get('/groceries/v1/mobile/money', headers=self.mobile).json()['summary'], {'spent_cents': 1})
        body = {'id': 'answer-0001', 'transaction': 'rv:v3', 'choice': 'confirm'}
        for _ in range(2): self.client.post('/groceries/v1/mobile/money/answers', json=body, headers=self.mobile)
        items = self.client.get('/v1/banking/answers', headers=self.owner).json()['items']
        self.assertEqual([(i['transaction'], i['choice']) for i in items], [('rv:v3', 'confirm')])
        self.client.post('/v1/banking/answers/ack', json={'through': items[-1]['sequence']}, headers=self.owner)
        self.assertEqual(self.client.get('/v1/banking/answers', headers=self.owner).json()['items'], [])


if __name__ == '__main__':
    unittest.main()
