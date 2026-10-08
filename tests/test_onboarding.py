import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import onboard_homeassistant as onboarding


class OnboardingTests(unittest.TestCase):
    def test_owner_is_created_privately_and_secrets_are_not_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / '.env').touch()
            (directory / 'secrets').mkdir()
            calls = []

            def api(path, payload=None, token=None, form=False):
                calls.append((path, payload, token))
                if path == '/api/onboarding':
                    return [{'step': step, 'done': False} for step in
                            ('user', 'core_config', 'integration', 'analytics')]
                if path == '/api/onboarding/users':
                    return {'auth_code': 'test-code'}
                if path == '/auth/token':
                    return {'access_token': 'test-access', 'refresh_token': 'test-refresh'}
                return {}

            with patch.object(onboarding, 'os', SimpleNamespace(name='posix', geteuid=lambda: 0)), \
                    patch.object(onboarding, 'request', side_effect=api):
                result = onboarding.onboard(directory, 'Example Owner')
            credentials = json.loads((directory / 'secrets/homeassistant-owner.json').read_text())
            self.assertGreaterEqual(len(credentials['password']), 32)
            self.assertNotIn(credentials['password'], json.dumps(result))
            self.assertNotIn('test-refresh', json.dumps(result))
            self.assertEqual(onboarding.BASE, 'http://127.0.0.1:8123')
            for path, payload, token in calls:
                if path.startswith('/api/onboarding/') and path != '/api/onboarding/users':
                    self.assertEqual(token, 'test-access')

    def test_existing_owner_without_saved_credentials_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / '.env').touch()
            (directory / 'secrets').mkdir()
            with patch.object(onboarding, 'os', SimpleNamespace(name='posix', geteuid=lambda: 0)), \
                    patch.object(onboarding, 'request', return_value=[{'step': 'user', 'done': True}]) as api:
                with self.assertRaisesRegex(ValueError, 'owner already exists'):
                    onboarding.onboard(directory, 'Example Owner')
                self.assertEqual(api.call_count, 1)
            self.assertFalse((directory / 'secrets/homeassistant-owner.json').exists())
