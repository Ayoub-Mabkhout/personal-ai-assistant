"""Offline Money relay and scheduler delivery contracts; no provider or model calls."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fastapi.testclient import TestClient

from personal_assistant.relay.api import create_app
from personal_assistant.relay.banking import ConsentReminderPump, ConversationQuestion
from personal_assistant.banking.ledger import Ledger
from personal_assistant.banking.agent import audit as auditor_audit

script = Path(__file__).resolve().parents[1] / 'scripts' / 'banking.py'
spec = importlib.util.spec_from_file_location('money_cli', script)
money_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(money_cli)


class Clock:
    def __init__(self, value): self.value = value
    def __call__(self): return self.value


class MoneyDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.clock = Clock(datetime(2026, 10, 18, tzinfo=timezone.utc).timestamp())
        self.app = create_app(root / 'queue.sqlite3', 's' * 40, 'w' * 40, clock=self.clock,
            groceries={'path': root / 'groceries.sqlite3', 'internal_token': 'g' * 40, 'assets': root},
            notifications={'public_url': 'https://assistant.example', 'native_provider': object()})
        devices = self.app.state.mobile_events.devices
        token = devices.exchange(devices.pairing()['code'], 'Offline test phone')['token']
        self.phone = {'Authorization': 'Bearer ' + token}
        self.owner = {'Authorization': 'Bearer ' + 's' * 40}
        self.worker = {'Authorization': 'Bearer ' + 'w' * 40}
        self.client = TestClient(self.app, base_url='https://testserver')

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_consent_projection_and_native_transport_are_separate(self):
        summary = {'spent_cents': 123, 'banks': [{'bank': 'Deutsche Bank', 'valid_until': '2026-11-01'}]}
        self.assertEqual(self.client.put('/v1/banking/summary', json=summary, headers=self.phone).status_code, 401)
        self.assertEqual(self.client.put('/v1/banking/summary', json=summary, headers=self.owner).status_code, 200)
        self.assertEqual(self.client.get('/v1/banking/summary', headers=self.phone).status_code, 401)
        self.assertEqual(self.client.get('/v1/banking/summary', headers=self.owner).json()['summary'], summary)
        state = self.client.get('/v1/banking/reminders/status', headers=self.owner).json()
        self.assertEqual(len(state['projected']), 1)
        self.assertIsNone(state['projected'][0]['native_event_queued_at'])
        self.assertFalse(state['handset_delivery_verified'])
        self.clock.value = state['projected'][0]['due']
        self.app.state.money_reminder_pump.tick()
        accepted = self.client.get('/v1/banking/reminders/status', headers=self.owner).json()
        self.assertIsNotNone(accepted['projected'][0]['native_event_queued_at'])
        self.assertFalse(accepted['handset_delivery_verified'])
        phone_id = self.app.state.mobile_events.devices.authenticate(self.phone['Authorization'][7:])
        events = self.app.state.mobile_events.events(phone_id)['items']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['payload']['type'], 'reminder')
        self.assertIn('Money', events[0]['payload']['title'])
        self.app.state.money_reminder_pump.tick()
        self.assertEqual(len(self.app.state.mobile_events.events(phone_id)['items']), 1)
        self.client.put('/v1/banking/summary', json=summary, headers=self.owner)
        self.assertIsNotNone(self.client.get('/v1/banking/reminders/status', headers=self.owner).json()['projected'][0]['native_event_queued_at'])
        renewed = {'banks': [{'bank': 'Deutsche Bank', 'valid_until': '2027-04-01'}]}
        self.client.put('/v1/banking/summary', json=renewed, headers=self.owner)
        self.assertIsNone(self.client.get('/v1/banking/reminders/status', headers=self.owner).json()['projected'][0]['native_event_queued_at'])

    def test_conversation_pairing_owner_auth_and_idempotent_receipts(self):
        url = '/groceries/v1/mobile/money/conversations'
        body = {'id': 'question-0001', 'text': 'Why was this counted as spending?'}
        self.assertEqual(self.client.post(url, json=body).status_code, 401)
        self.assertEqual(self.client.post(url, json=body, headers=self.worker).status_code, 401)
        self.assertEqual(self.client.post(url, json=body, headers=self.phone).status_code, 200)
        self.assertEqual(self.client.post(url, json=body, headers=self.phone).status_code, 200)
        self.assertEqual(self.client.post(url, json={**body, 'text': 'Different'}, headers=self.phone).status_code, 409)
        pending = self.client.get('/v1/banking/conversations/pending', headers=self.owner).json()['items']
        self.assertEqual([(item['id'], item['text']) for item in pending], [(body['id'], body['text'])])
        self.assertEqual(self.client.get('/v1/banking/conversations/pending', headers=self.phone).status_code, 401)
        self.client.post('/v1/banking/conversations/question-0001/ack', headers=self.owner)
        self.client.post('/v1/banking/conversations/question-0001/ack', headers=self.owner)
        self.assertEqual(self.client.get('/v1/banking/conversations/pending', headers=self.owner).json()['items'], [])
        answer = {'text': 'The auditor will explain this transaction.'}
        self.client.put('/v1/banking/conversations/question-0001/answer', json=answer, headers=self.owner)
        self.client.put('/v1/banking/conversations/question-0001/answer', json=answer, headers=self.owner)
        self.assertEqual(self.client.put('/v1/banking/conversations/question-0001/answer', json={'text': 'Changed'}, headers=self.owner).status_code, 409)
        self.assertEqual(self.client.get(url + '/question-0001', headers=self.phone).json()['answer'], answer['text'])
        self.assertEqual(self.client.get('/v1/banking/conversations', headers=self.owner).json()['items'][0]['id'], body['id'])

    def test_phone_answer_idempotency_rejects_conflicting_retry(self):
        path = '/groceries/v1/mobile/money/answers'
        answer = {'id': 'answer-unique-01', 'transaction': 'db:market-1', 'choice': 'confirm'}
        self.assertEqual(self.client.post(path, json=answer, headers=self.phone).status_code, 200)
        self.assertEqual(self.client.post(path, json=answer, headers=self.phone).status_code, 200)
        self.assertEqual(self.client.post(path, json={**answer, 'choice': 'expense'}, headers=self.phone).status_code, 409)
        items = self.client.get('/v1/banking/answers', headers=self.owner).json()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['choice'], 'confirm')

    def test_owner_browser_conversation_requires_same_origin(self):
        token = 'browser-session-opaque-test'
        with self.app.state.owner_auth.db() as db:
            db.execute('INSERT INTO owner_sessions VALUES(?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), time.time() + 600))
        self.client.cookies.set('assistant_owner', token)
        self.assertEqual(self.client.get('/v1/banking/summary').status_code, 200)
        body = {'id': 'browser-question-01', 'text': 'How much is left?'}
        self.assertEqual(self.client.post('/v1/banking/conversations', json=body).status_code, 403)
        self.assertEqual(self.client.post('/v1/banking/conversations', json=body,
                                          headers={'Origin': 'https://testserver'}).status_code, 200)

    def test_consent_delivery_failure_retries_without_losing_projection(self):
        self.client.put('/v1/banking/summary', json={'banks': [{'bank': 'Revolut', 'valid_until': '2026-11-01'}]},
                        headers=self.owner)
        self.clock.value = self.app.state.banking.reminder_status()['projected'][0]['due']
        def failed(_): raise OSError('offline')
        ConsentReminderPump(self.app.state.banking, failed).tick()
        state = self.app.state.banking.reminder_status()['projected'][0]
        self.assertEqual(state['attempts'], 1)
        self.assertIsNone(state['native_event_queued_at'])
        sent = []
        ConsentReminderPump(self.app.state.banking, sent.append).tick()
        self.assertEqual(sent, [])
        self.clock.value += 2
        ConsentReminderPump(self.app.state.banking, sent.append).tick()
        self.assertEqual(len(sent), 1)
        self.assertIsNotNone(self.app.state.banking.reminder_status()['projected'][0]['native_event_queued_at'])

    def test_cli_question_queue_ack_then_reply_without_model(self):
        class Relay:
            def __init__(self, client, owner): self.client, self.owner = client, owner
            def call(self, path, payload=None, method=None):
                response = self.client.request(method or ('POST' if payload is not None else 'GET'),
                                               path.removeprefix('/relay'), json=payload, headers=self.owner)
                response.raise_for_status()
                return response.json()
        class Ledger:
            def __init__(self): self.saved = {}; self.output = {}
            def enqueue(self, kind, key, payload):
                self.saved.setdefault(key, (len(self.saved) + 1, payload))
                return self.saved[key][0]
            def audit_output(self, seq): return self.output.get(seq)
        relay, ledger = Relay(self.client, self.owner), Ledger()
        question = {'id': 'question-0002', 'text': 'Explain the rent trend.'}
        self.client.post('/groceries/v1/mobile/money/conversations', json=question, headers=self.phone)
        self.assertEqual(money_cli.collect_questions(relay, ledger), 1)
        self.assertEqual(money_cli.collect_questions(relay, ledger), 0)
        self.assertEqual(ledger.saved[question['id']][1]['text'], question['text'])
        self.assertEqual(money_cli.publish_replies(relay, ledger), 0)
        ledger.output[ledger.saved[question['id']][0]] = 'Rent rose after the renewal.'
        self.assertEqual(money_cli.publish_replies(relay, ledger), 1)
        self.assertEqual(money_cli.publish_replies(relay, ledger), 0)
        self.assertEqual(self.client.get('/groceries/v1/mobile/money/conversations/question-0002',
                                         headers=self.phone).json()['answer'], 'Rent rose after the renewal.')

    def test_reply_publication_pages_past_unanswered_questions(self):
        class Relay:
            def call(inner, path, payload=None, method=None):
                response = self.client.request(method or ('POST' if payload is not None else 'GET'),
                                               path.removeprefix('/relay'), json=payload, headers=self.owner)
                response.raise_for_status()
                return response.json()
        class Ledger:
            def enqueue(self, kind, key, payload): return int(key[-4:]) + 1
            def audit_output(self, seq): return 'Last answer.' if seq == 101 else None
        for number in range(101):
            self.app.state.banking.ask(ConversationQuestion(id='question-%04d' % number, text='Synthetic question'))
        self.assertEqual(money_cli.publish_replies(Relay(), Ledger()), 1)
        self.assertEqual(self.client.get('/groceries/v1/mobile/money/conversations/question-0100',
                                         headers=self.phone).json()['answer'], 'Last answer.')

    def test_watch_rejects_more_frequent_unattended_schedule(self):
        with self.assertRaisesRegex(ValueError, 'six hours'):
            money_cli.watch({}, None, 21599)

    def test_unattended_run_without_linked_accounts_publishes_without_bank_or_model(self):
        class Relay:
            def call(inner, path, payload=None, method=None):
                response = self.client.request(method or ('POST' if payload is not None else 'GET'),
                                               path.removeprefix('/relay'), json=payload, headers=self.owner)
                response.raise_for_status()
                return response.json()
        ledger = Ledger(Path(self.temp.name) / 'local-ledger.sqlite3')
        report = money_cli.run_once({}, ledger, Relay())
        self.assertEqual(report['sync'], [])
        self.assertEqual(report['decided'], 0)
        self.assertIsNotNone(self.client.get('/v1/banking/summary', headers=self.owner).json()['summary'])

    def test_transaction_to_auditor_summary_and_phone_reply_end_to_end(self):
        class Relay:
            def call(inner, path, payload=None, method=None):
                response = self.client.request(method or ('POST' if payload is not None else 'GET'),
                                               path.removeprefix('/relay'), json=payload, headers=self.owner)
                response.raise_for_status()
                return response.json()
        class Provider:
            def __init__(self): self.fetches = 0
            def transactions(self, account, since):
                self.fetches += 1
                return [{'entry_reference': 'market-%d' % i, 'transaction_amount': {'amount': '12.50', 'currency': 'EUR'},
                         'credit_debit_indicator': 'DBIT', 'status': 'BOOK', 'booking_date': date.today().isoformat(),
                         'creditor': {'name': 'Market'}, 'remittance_information': ['Groceries']}
                        for i in range(61)]
        ledger = Ledger(Path(self.temp.name) / 'auditor-ledger.sqlite3')
        ledger.link('Deutsche Bank', 'DE', {'session_id': 'synthetic-session',
                    'access': {'valid_until': (date.today() + timedelta(days=30)).isoformat()},
                    'accounts': [{'uid': 'db', 'account_id': {'iban': 'DE00SYNTHETIC'}, 'currency': 'EUR'}]})
        question = {'id': 'money-question-123', 'text': 'Why did groceries count against my allowance?'}
        self.client.post('/groceries/v1/mobile/money/conversations', json=question, headers=self.phone)
        provider, calls = Provider(), []
        def fake_ask(prompt, config, session, on_start):
            payload = json.loads(prompt)
            calls.append(payload)
            self.assertEqual({j['kind'] for j in payload['jobs']}, {'transaction', 'question'})
            self.assertEqual(len(payload['transactions_for_review']), 61)
            job = next(j for j in payload['jobs'] if j['kind'] == 'question')
            return ({'decisions': [{'id': row['id'], 'kind': 'expense', 'category': 'Groceries',
                                    'counts': True, 'linked': [], 'reasoning': 'A grocery purchase.',
                                    'confidence': 0.98, 'question': '', 'recurring': False,
                                    'monthly_cents': None, 'coverage_months': [], 'series_key': None}
                                   for row in payload['transactions_for_review']],
                     'insights': [], 'replies': [{'job_seq': job['seq'],
                                                 'text': 'It was a grocery purchase, so it counts as elective spending.'}]},
                    'synthetic-codex-session')
        def offline_audit(store, config):
            return auditor_audit(store, config, today=date.today(), ask=fake_ask)
        with patch.object(money_cli.service, 'provider', return_value=provider), patch.object(money_cli, 'audit', offline_audit):
            first = money_cli.run_once({}, ledger, Relay())
            self.assertEqual((first['decided'], first['questions'], first['replies']), (61, 1, 1))
            for _ in range(3): money_cli.run_once({}, ledger, Relay())
            fifth = money_cli.run_once({}, ledger, Relay())
        self.assertEqual(provider.fetches, 4)
        self.assertEqual(fifth['sync'][0]['skipped'], 'daily limit')
        self.assertEqual(len(calls), 1)
        summary = self.client.get('/groceries/v1/mobile/money', headers=self.phone).json()['summary']
        self.assertEqual(summary['spent_cents'], 61 * 1250)
        self.assertEqual(len(summary['transactions']), 61)
        self.assertEqual(summary['transactions'][0]['category'], 'Groceries')
        self.assertEqual(self.client.get('/groceries/v1/mobile/money/conversations/money-question-123',
                                         headers=self.phone).json()['answer'],
                         'It was a grocery purchase, so it counts as elective spending.')


if __name__ == '__main__': unittest.main()
