import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from scripts.prepare_server import prepare, publish


class ServerSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / 'server'
        # Preparation normally runs as root and sets container ownership. These
        # isolated template tests use temp files, without sudo or real chown.
        for operation in (patch('scripts.prepare_server.os.geteuid', return_value=0, create=True),
                          patch('scripts.prepare_server.os.chown', create=True)):
            operation.start()
            self.addCleanup(operation.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_prepare_preserves_credentials_and_owner_configuration(self):
        prepare(self.directory, 'assistant.example.com', 'owner@example.com')
        token = (self.directory / 'secrets/submit_token').read_bytes()
        configuration = self.directory / 'data/relay/owner-login.json'
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
        auth = self.directory / 'data/relay/owner-login.json'
        auth.write_text(json.dumps({}))
        with self.assertRaises(ValueError):
            publish(self.directory)
        auth.write_text(json.dumps({'username':'owner','salt':'0'*32,'password_hash':'0'*128}))
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

    def test_nonroot_preparation_still_fails_before_creating_files(self):
        with patch('scripts.prepare_server.os', wraps=os) as host_os:
            host_os.name = 'posix'
            host_os.geteuid.return_value = 1000
            with self.assertRaisesRegex(ValueError, 'sudo'):
                prepare(self.directory, 'assistant.example.com', 'owner@example.com')
        self.assertFalse(self.directory.exists())

    def test_isolated_posix_preparation_requests_container_ownership(self):
        host_os = SimpleNamespace(**vars(os))
        host_os.name = 'posix'
        host_os.geteuid = lambda: 0
        host_os.chown = Mock()
        with patch('scripts.prepare_server.os', host_os):
            prepare(self.directory, 'assistant.example.com', 'owner@example.com')
        directory = self.directory.resolve()
        self.assertEqual(host_os.chown.call_args_list, [
            call(directory / 'data/relay', 10001, 10001),
            *[call(directory / 'secrets' / name, 0, 10001)
              for name in ('submit_token', 'worker_token', 'groceries_token')],
        ])


if __name__ == '__main__':
    unittest.main()
