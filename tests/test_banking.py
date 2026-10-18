from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fastapi.testclient import TestClient

from personal_assistant.banking import service
from personal_assistant.banking.agent import audit
from personal_assistant.banking.ledger import Ledger, normalise, summarise
from personal_assistant.relay.api import create_app


def raw(reference, amount, debit, day, name='', status='BOOK', text='', iban=''):
    party = {'name': name}
    item = {'transaction_amount': {'amount': amount, 'currency': 'EUR'}, 'credit_debit_indicator': 'DBIT' if debit else 'CRDT',
            'status': status, 'booking_date': day, 'remittance_information': [text] if text else [],
            ('creditor' if debit else 'debtor'): party}
    if iban: item['creditor_account' if debit else 'debtor_account'] = {'iban': iban}
    if reference: item['entry_reference'] = reference
    return item


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
            self.ledger.decide(identity, kind, category, counts, [], 'test', 0.9, 'Sure?' if identity == 'rv:v3' else '', 'ai')
        total = summarise(self.ledger, date(2026, 10, 18))
        self.assertEqual((total['spent_cents'], total['remaining_cents']), (2400, 117600))
        self.assertEqual(total['net_cents'], 294000 - 90000 - 4800 + 2400)
        self.assertEqual(total['period']['days_left'], 14)
        self.assertEqual(total['safe_per_day_cents'], 117600 // 14)
        self.assertEqual(total['categories'], [{'name': 'Eating out', 'cents': 2400}])
        self.assertEqual([r['id'] for r in total['review']], ['rv:v3'])
        # The owner's word stands against a later agent revision.
        rows = {r['id']: r for r in self.ledger.transactions()}
        self.assertTrue(service.answer(self.ledger, rows['rv:v3'], 'confirm'))
        self.assertFalse(self.ledger.decide('rv:v3', 'income', '', False, [], 'x', 0.5, '', 'ai'))
        self.assertEqual(summarise(self.ledger, date(2026, 10, 18))['review'], [])

    def test_audit_applies_model_decisions_and_never_overrides_the_owner(self):
        self.ledger.store('rv', [raw('v1', '10', True, '2026-10-05', 'Cafe'), raw('v2', '5', True, '2026-10-06', 'Cafe')], '2026-10-01')
        seen = []

        def ask(prompt, config):
            seen.append(json.loads(prompt))
            return {'decisions': [{'id': i, 'kind': 'expense', 'category': 'Eating out', 'counts': True, 'linked': [],
                                   'reasoning': 'Coffee.', 'confidence': 1.4, 'question': ''} for i in ('rv:v1', 'rv:v2', 'rv:unknown')],
                    'insights': [{'kind': 'pace', 'text': 'On track.'}]}
        decided, insights = audit(self.ledger, {}, date(2026, 10, 18), ask=ask)
        self.assertEqual(decided, 2)
        self.assertEqual(seen[0]['allowance']['amount'], '1200.00')
        self.assertEqual({r['confidence'] for r in self.ledger.transactions()}, {1.0})
        self.assertEqual(self.ledger.setting('insights'), insights)
        self.assertEqual(audit(self.ledger, {}, ask=ask), (0, None))


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
