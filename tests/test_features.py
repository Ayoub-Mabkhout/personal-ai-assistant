import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import personal_assistant.dashboard as dashboard
from personal_assistant.relay.api import create_app
from personal_assistant.relay.features import Features
from personal_assistant.worker.runtime import TransportError


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): self.now += 1; return self.now


class FeatureStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Features(Path(self.temp.name)/'features.sqlite3', clock=Clock())

    def tearDown(self):
        self.temp.cleanup()

    def test_new_store_is_empty_and_creation_is_idempotent_on_client_id(self):
        self.assertEqual(self.store.snapshot(), {'revision': 0, 'items': []})
        item, created = self.store.create({'id': 'feature-0001', 'title': '  Shared   checklist ', 'area': 'dashboard'})
        self.assertTrue(created)
        self.assertEqual({k: item[k] for k in ('id', 'title', 'detail', 'area', 'done', 'done_at')},
                         {'id': 'feature-0001', 'title': 'Shared checklist', 'detail': '', 'area': 'dashboard', 'done': False, 'done_at': None})
        again, created = self.store.create({'id': 'feature-0001', 'title': 'Different replay text'})
        self.assertFalse(created)
        self.assertEqual(again, item)
        self.assertEqual(self.store.snapshot()['revision'], 1)
        generated, _ = self.store.create({'title': 'Server generated'})
        self.assertRegex(generated['id'], r'^[0-9a-f-]{36}$')
        self.assertEqual(generated['area'], 'assistant')
        with self.assertRaises(ValueError):
            self.store.create({'title': '   '})

    def test_open_items_keep_plan_order_and_finished_items_are_newest_first(self):
        for number in range(1, 5):
            self.store.create({'id': f'feature-000{number}', 'title': f'Feature {number}'})
        self.store.update('feature-0003', {'done': True})
        self.store.update('feature-0001', {'done': True})
        snapshot = self.store.snapshot()
        self.assertEqual([x['id'] for x in snapshot['items']], ['feature-0002', 'feature-0004', 'feature-0001', 'feature-0003'])
        self.assertEqual([x['done'] for x in snapshot['items']], [False, False, True, True])
        finished = self.store.update('feature-0001', {'done': True})
        self.assertEqual(finished['done_at'], snapshot['items'][2]['done_at'])
        self.assertEqual(self.store.snapshot()['revision'], snapshot['revision'])
        reopened = self.store.update('feature-0001', {'done': False, 'title': 'Renamed', 'detail': ' Notes ', 'area': 'companion'})
        self.assertEqual((reopened['done'], reopened['done_at'], reopened['title'], reopened['detail'], reopened['area']),
                         (False, None, 'Renamed', 'Notes', 'companion'))
        self.assertGreater(reopened['updated'], reopened['created'])
        self.assertEqual([x['id'] for x in self.store.snapshot()['items']][:3], ['feature-0001', 'feature-0002', 'feature-0004'])
        with self.assertRaises(KeyError):
            self.store.update('feature-9999', {'done': True})

    def test_delete_is_idempotent_and_a_late_replay_cannot_revive_the_entry(self):
        self.store.create({'id': 'feature-0001', 'title': 'Remove me'})
        self.assertEqual(self.store.delete('feature-0001'), {'deleted': True})
        revision = self.store.snapshot()['revision']
        self.assertEqual(self.store.delete('feature-0001'), {'deleted': True})
        self.assertEqual(self.store.snapshot(), {'revision': revision, 'items': []})
        with self.assertRaises(ValueError):
            self.store.create({'id': 'feature-0001', 'title': 'Remove me'})


class RelayFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(root/'queue.sqlite3', 's'*40, 'w'*40,
            groceries={'path': root/'groceries.sqlite3', 'internal_token': 'g'*40,
                       'assets': root})
        devices = self.app.state.mobile_events.devices
        self.phone = devices.exchange(devices.pairing()['code'], 'Synthetic phone')
        self.devices = devices
        self.client = TestClient(self.app)
        self.mobile = {'Authorization': 'Bearer '+self.phone['token']}
        self.owner = {'Authorization': 'Bearer '+'s'*40}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_phone_and_dashboard_mounts_share_one_authenticated_store(self):
        phone, owner = '/groceries/v1/mobile/features', '/v1/features'
        for path, wrong in ((phone, self.owner), (owner, self.mobile), (phone, {'Authorization': 'Bearer '+'g'*40})):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
                self.assertEqual(self.client.get(path, headers=wrong).status_code, 401)
        response = self.client.post(phone, headers=self.mobile, json={'id': 'phone-feature-1', 'title': 'Offline add', 'area': 'companion'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.post(phone, headers=self.mobile, json={'id': 'phone-feature-1', 'title': 'Offline add', 'area': 'companion'}).status_code, 200)
        listing = self.client.get(owner, headers=self.owner)
        self.assertEqual(listing.headers['cache-control'], 'private, no-store')
        self.assertEqual(listing.json()['revision'], 1)
        self.assertEqual([x['title'] for x in listing.json()['items']], ['Offline add'])
        done = self.client.patch(owner+'/phone-feature-1', headers=self.owner, json={'done': True}).json()
        self.assertTrue(done['done'])
        self.assertIsInstance(done['done_at'], float)
        self.assertEqual(self.client.get(phone, headers=self.mobile).json()['items'][0]['done_at'], done['done_at'])
        self.devices.revoke(self.phone['id'])
        self.assertEqual(self.client.get(phone, headers=self.mobile).status_code, 401)

    def test_post_aliases_validation_and_missing_entries(self):
        base = '/groceries/v1/mobile/features'
        created = self.client.post(base, headers=self.mobile, json={'title': 'Generated ID'}).json()
        alias = self.client.post(base+'/'+created['id'], headers=self.mobile, json={'done': True})
        self.assertEqual(alias.status_code, 200)
        self.assertTrue(alias.json()['done'])
        self.assertEqual(self.client.post(base+'/'+created['id'], headers=self.mobile, json={'done': False}).json()['done_at'], None)
        for body in ({}, {'title': ''}, {'title': 'x'*201}, {'title': 'ok', 'area': 'phone'}, {'title': 'ok', 'detail': 'x'*1001},
                     {'title': 'ok', 'id': 'short'}, {'title': 'ok', 'extra': 1}, {'title': 7}, {'title': '   '}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post(base, headers=self.mobile, json=body).status_code, 422)
        for body in ({'done': 'true'}, {'done': 1}, {'title': ''}, {'area': 'nowhere'}, {'unknown': True}):
            with self.subTest(edit=body):
                self.assertEqual(self.client.patch(base+'/'+created['id'], headers=self.mobile, json=body).status_code, 422)
        self.assertEqual(self.client.patch(base+'/missing-feature', headers=self.mobile, json={'done': True}).status_code, 404)
        self.assertEqual(self.client.patch(base+'/bad.id', headers=self.mobile, json={'done': True}).status_code, 404)
        self.assertEqual(self.client.delete(base+'/'+created['id'], headers=self.mobile).json(), {'deleted': True})
        self.assertEqual(self.client.post(base+'/'+created['id']+'/delete', headers=self.mobile).json(), {'deleted': True})
        self.assertEqual(self.client.delete(base+'/never-existed', headers=self.mobile).json(), {'deleted': True})
        replay = self.client.post(base, headers=self.mobile, json={'id': created['id'], 'title': 'Generated ID'})
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(self.client.get(base, headers=self.mobile).json()['items'], [])


class DashboardFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        relay = TestClient(create_app(root/'queue.sqlite3', 's'*40, 'w'*40))
        self.relay = relay
        self.calls = []

        class FakeRelay:
            # Routes the dashboard's relay calls into an in-process relay, with no network.
            def __init__(inner, base, token_file, timeout=8): pass
            def call(inner, path, payload=None, method=None):
                self.calls.append((method or ('POST' if payload is not None else 'GET'), path))
                response = relay.request(method or ('POST' if payload is not None else 'GET'), path,
                                         json=payload, headers={'Authorization': 'Bearer '+'s'*40})
                if response.status_code >= 400: raise TransportError(response.status_code)
                return response.json()
        self.patch = patch.object(dashboard, 'RelayClient', FakeRelay)
        self.patch.start()
        config = {'runtime_dir': str(root/'runtime'), 'relay_url': 'https://relay.example', 'submit_token_file': str(root/'unused')}
        self.client = TestClient(dashboard.create_app(config), base_url='http://127.0.0.1:8787')
        self.token = re.search(r"const token='(.+?)'", self.client.get('/').text)[1]
        self.headers = {'X-Dashboard-Token': self.token}

    def tearDown(self):
        self.client.close()
        self.relay.close()
        self.patch.stop()
        self.temp.cleanup()

    def test_dashboard_checks_an_item_and_it_moves_to_finished(self):
        self.assertEqual(self.client.get('/api/features').status_code, 401)
        for title in ('First', 'Second'):
            self.assertEqual(self.client.post('/api/features', headers=self.headers, json={'id': 'dash-'+title.lower()+'-1', 'title': title}).status_code, 200)
        checked = self.client.patch('/api/features/dash-first-1', headers=self.headers, json={'done': True})
        self.assertTrue(checked.json()['done'])
        listing = self.client.get('/api/features', headers=self.headers).json()
        self.assertEqual([(x['title'], x['done']) for x in listing['items']], [('Second', False), ('First', True)])
        self.assertIn(('PATCH', '/v1/features/dash-first-1'), self.calls)
        self.assertEqual(self.client.patch('/api/features/missing-entry', headers=self.headers, json={'done': True}).status_code, 404)
        self.assertEqual(self.client.patch('/api/features/bad.id', headers=self.headers, json={'done': True}).status_code, 404)
        self.assertEqual(self.client.post('/api/features', headers=self.headers, json={'title': ''}).status_code, 422)
        self.assertEqual(self.client.delete('/api/features/dash-first-1', headers=self.headers).json(), {'deleted': True})
        self.assertEqual(self.client.post('/api/features', headers=self.headers, json={'id': 'dash-first-1', 'title': 'First'}).status_code, 409)
        self.assertEqual(self.client.post('/api/features', headers=self.headers, json={'title': 'x'}, ).status_code, 200)
        cross = self.client.post('/api/features', headers={**self.headers, 'Origin': 'https://elsewhere.example'}, json={'title': 'x'})
        self.assertEqual(cross.status_code, 403)

    def test_unconfigured_or_unreachable_relay_is_reported_honestly(self):
        with tempfile.TemporaryDirectory() as raw:
            client = TestClient(dashboard.create_app({'runtime_dir': raw}), base_url='http://127.0.0.1:8787')
            token = re.search(r"const token='(.+?)'", client.get('/').text)[1]
            response = client.get('/api/features', headers={'X-Dashboard-Token': token})
            self.assertEqual(response.status_code, 503)
            client.close()
        class Down:
            def __init__(self, *args, **kwargs): pass
            def call(self, *args, **kwargs): raise TransportError()
        with patch.object(dashboard, 'RelayClient', Down):
            response = self.client.patch('/api/features/dash-first-1', headers=self.headers, json={'done': True})
        self.assertEqual(response.status_code, 503)
        self.assertIn('not confirmed', response.json()['detail'])


class FeatureImportTests(unittest.TestCase):
    def test_import_is_repeatable_and_never_overwrites_or_revives(self):
        spec = importlib.util.spec_from_file_location('import_features_cli', Path(__file__).resolve().parents[1]/'scripts/import_features.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as raw:
            relay = TestClient(create_app(Path(raw)/'queue.sqlite3', 's'*40, 'w'*40))

            class Client:
                def call(self, path, payload=None, method=None):
                    response = relay.request(method or ('POST' if payload is not None else 'GET'), path,
                                             json=payload, headers={'Authorization': 'Bearer '+'s'*40})
                    if response.status_code >= 400: raise TransportError(response.status_code)
                    return response.json()
            source = [{'title': 'Synthetic one', 'area': 'companion'}, {'title': 'Synthetic two', 'done': True},
                      {'id': 'explicit-0001', 'title': 'Synthetic three', 'detail': 'Generic sample'}]
            self.assertEqual(module.run(Client(), source), {'added': 3, 'already_present': 0, 'previously_deleted': 0})
            items = relay.get('/v1/features', headers={'Authorization': 'Bearer '+'s'*40}).json()['items']
            self.assertEqual([(x['title'], x['done']) for x in items], [('Synthetic one', False), ('Synthetic three', False), ('Synthetic two', True)])
            first = items[0]['id']
            relay.patch('/v1/features/'+first, json={'done': True}, headers={'Authorization': 'Bearer '+'s'*40})
            relay.delete('/v1/features/explicit-0001', headers={'Authorization': 'Bearer '+'s'*40})
            self.assertEqual(module.run(Client(), source), {'added': 0, 'already_present': 2, 'previously_deleted': 1})
            items = relay.get('/v1/features', headers={'Authorization': 'Bearer '+'s'*40}).json()['items']
            self.assertEqual(len(items), 2)
            self.assertTrue(all(x['done'] for x in items))
            for bad in ({'title': 'x'}, [{'title': ''}], [{'title': 'x', 'done': 'yes'}], ['text']):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        module.entries(bad)
            relay.close()


if __name__ == '__main__':
    unittest.main()
