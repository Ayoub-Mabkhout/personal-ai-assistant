import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_server import prepare, publish


class ServerSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / 'server'

    def tearDown(self):
        self.temp.cleanup()

    def test_prepare_preserves_credentials_and_owner_configuration(self):
        prepare(self.directory, 'assistant.example.com', 'owner@example.com')
        token = (self.directory / 'secrets/submit_token').read_bytes()
        configuration = self.directory / 'data/homeassistant/configuration.yaml'
        configuration.write_text('existing user configuration')
        prepare(self.directory, 'assistant.example.com', 'owner@example.com')
        self.assertEqual((self.directory / 'secrets/submit_token').read_bytes(), token)
        self.assertEqual(configuration.read_text(), 'existing user configuration')
        self.assertIn('Caddyfile.bootstrap', (self.directory / '.env').read_text())
        self.assertNotIn(token.decode().strip(), (self.directory / '.env').read_text())

    def test_public_access_requires_active_owner(self):
        prepare(self.directory, 'assistant.example.com', 'owner@example.com')
        with self.assertRaises(ValueError):
            publish(self.directory)
        auth = self.directory / 'data/homeassistant/.storage/auth'
        auth.parent.mkdir()
        auth.write_text(json.dumps({'data': {'users': [{'is_owner': True, 'is_active': False}]}}))
        with self.assertRaises(ValueError):
            publish(self.directory)
        auth.write_text(json.dumps({'data': {'users': [{'is_owner': True, 'is_active': True}]}}))
        publish(self.directory)
        self.assertIn('ASSISTANT_CADDY_CONFIG=Caddyfile\n', (self.directory / '.env').read_text())
        self.assertNotIn('Caddyfile.bootstrap', (self.directory / '.env').read_text())

    def test_invalid_hostnames_and_changed_domains_are_rejected(self):
        for domain in ('https://example.com', 'example.com/attack', 'example.com\nX=1', '*.example.com'):
            with self.assertRaises(ValueError):
                prepare(self.directory, domain, 'owner@example.com')
        prepare(self.directory, 'assistant.example.com', 'owner@example.com')
        with self.assertRaises(ValueError):
            prepare(self.directory, 'other.example.com', 'owner@example.com')


if __name__ == '__main__':
    unittest.main()
