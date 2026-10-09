import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from personal_assistant.relay.api import create_app
from personal_assistant.relay.mobile_settings import MobileSettings


class MobileSettingsTests(unittest.TestCase):
    def test_missing_invalid_and_incomplete_configuration_follows_system(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'companion-preferences.json'
            store = MobileSettings(path)
            self.assertEqual(store.snapshot(), {'daylight': None})
            self.assertFalse(path.exists())
            invalid = [None, [], {}, {'daylight': {}}, {'daylight': {'latitude': 0}},
                       {'daylight': {'latitude': True, 'longitude': 0}},
                       {'daylight': {'latitude': '0', 'longitude': 0}},
                       {'daylight': {'latitude': 91, 'longitude': 0}},
                       {'daylight': {'latitude': 0, 'longitude': -181}},
                       {'daylight': {'latitude': float('nan'), 'longitude': 0}},
                       {'daylight': {'latitude': 0, 'longitude': float('inf')}}]
            for value in invalid:
                with self.subTest(value=value):
                    path.write_text(json.dumps(value), encoding='utf-8')
                    self.assertEqual(store.snapshot(), {'daylight': None})
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(store.snapshot(), {'daylight': None})
            path.write_bytes(b' ' * 4097)
            self.assertEqual(store.snapshot(), {'daylight': None})

    def test_whitelist_reload_and_zero_coordinates_do_not_disclose_other_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'companion-preferences.json'
            store = MobileSettings(path)
            raw = json.dumps({'daylight': {'latitude': 0, 'longitude': 0, 'private_label': 'synthetic'},
                              'other_private_setting': 'synthetic'}).encode()
            path.write_bytes(raw)
            self.assertEqual(store.snapshot(), {'daylight': {'latitude': 0, 'longitude': 0}})
            self.assertEqual(path.read_bytes(), raw)
            path.write_text(json.dumps({'daylight': {'latitude': -20.5, 'longitude': 130.25}}))
            self.assertEqual(store.snapshot(), {'daylight': {'latitude': -20.5, 'longitude': 130.25}})
            path.unlink()
            self.assertEqual(store.snapshot(), {'daylight': None})

    def test_paired_read_only_endpoint_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured = root / 'companion-preferences.json'
            configured.write_text(json.dumps({'daylight': {'latitude': 0, 'longitude': 0}}))
            app = create_app(root / 'queue.sqlite3', 'o' * 40, 'w' * 40,
                groceries={'path': root / 'groceries.sqlite3', 'internal_token': 'g' * 40,
                           'ha_url': 'http://homeassistant:8123', 'assets': root})
            devices = app.state.mobile_events.devices
            phone = devices.exchange(devices.pairing()['code'], 'Synthetic phone')
            auth = {'Authorization': 'Bearer ' + phone['token']}
            client = TestClient(app)
            endpoint = '/groceries/v1/mobile/preferences'
            self.assertEqual(client.get(endpoint).status_code, 401)
            self.assertEqual(client.get(endpoint, headers={'Authorization': 'Bearer ' + 'o' * 40}).status_code, 401)
            response = client.get(endpoint, headers=auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'daylight': {'latitude': 0, 'longitude': 0}})
            self.assertEqual(response.headers['cache-control'], 'private, no-store')
            self.assertEqual(client.post(endpoint, headers=auth, json={'daylight': None}).status_code, 405)
            self.assertEqual(MobileSettings(configured).snapshot(), response.json())
            devices.revoke(phone['id'])
            self.assertEqual(client.get(endpoint, headers=auth).status_code, 401)

    def test_explicit_protected_path_overrides_default_without_exposing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            override = root / 'protected' / 'preferences.json'
            override.parent.mkdir()
            override.write_text(json.dumps({'daylight': {'latitude': 10, 'longitude': -20}}))
            app = create_app(root / 'queue.sqlite3', 'o' * 40, 'w' * 40, mobile_settings_file=override,
                groceries={'path': root / 'groceries.sqlite3', 'internal_token': 'g' * 40,
                           'ha_url': 'http://homeassistant:8123', 'assets': root})
            devices = app.state.mobile_events.devices
            phone = devices.exchange(devices.pairing()['code'], 'Synthetic phone')
            response = TestClient(app).get('/groceries/v1/mobile/preferences',
                headers={'Authorization': 'Bearer ' + phone['token']})
            self.assertEqual(response.json(), {'daylight': {'latitude': 10, 'longitude': -20}})
            self.assertNotIn(str(override), response.text)
            self.assertFalse((root / 'companion-preferences.json').exists())
