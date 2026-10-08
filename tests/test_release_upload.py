import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from personal_assistant.groceries.releases import ReleaseFeed
from personal_assistant.relay.release_upload import release_upload_router


class ReleaseUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.token = 'publisher-only-test-token-' * 3
        token_path = self.root / 'publish-token.txt'
        token_path.write_text(self.token)
        self.feed = ReleaseFeed(self.root / 'companion.apk')
        app = FastAPI()
        app.include_router(release_upload_router(self.feed, token_path))
        self.client = TestClient(app)

    def tearDown(self):
        self.temp.cleanup()

    def artifact(self, version=6, marker=b'generic-code', extra=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('AndroidManifest.xml', '<manifest package="com.personalassistant.companion"/>')
            archive.writestr('classes.dex', marker)
            for name, value in (extra or {}).items():
                archive.writestr(name, value)
        data = output.getvalue()
        metadata = {'package_name': 'com.personalassistant.companion', 'version_code': version,
                    'version_name': f'0.{version}.0', 'min_sdk': 26, 'size': len(data),
                    'sha256': hashlib.sha256(data).hexdigest()}
        return data, metadata

    def put(self, data, metadata, token=None):
        return self.client.put('/companion/v1/releases/artifact', content=data, headers={
            'Authorization': 'Bearer ' + (self.token if token is None else token),
            'X-Release-Manifest': base64.b64encode(json.dumps(metadata).encode()).decode()})

    def test_narrow_auth_publication_and_exact_retry(self):
        data, metadata = self.artifact()
        self.assertEqual(self.put(data, metadata, 'wrong').status_code, 401)
        self.assertFalse(self.feed.apk.exists())
        first = self.put(data, metadata)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()['sha256'], metadata['sha256'])
        self.assertEqual(first.json()['state'], 'pending')
        self.assertTrue(first.json()['created'])
        self.assertEqual(self.feed.apk.read_bytes(), data)
        retry = self.put(data, metadata).json()
        self.assertFalse(retry['created'])
        self.assertFalse(retry['artifact_changed'])
        self.assertEqual(self.client.get('/v1/agent/prompts', headers={'Authorization': 'Bearer '+self.token}).status_code, 404)

    def test_failed_hash_does_not_replace_existing_release(self):
        data, metadata = self.artifact(5)
        self.assertEqual(self.put(data, metadata).status_code, 201)
        new_data, new_meta = self.artifact(6)
        new_meta['sha256'] = '0' * 64
        self.assertEqual(self.put(new_data, new_meta).status_code, 400)
        self.assertEqual(self.feed.apk.read_bytes(), data)
        self.assertEqual(self.feed.manifest()['version_code'], 5)
        self.assertFalse(list(self.root.glob('.companion-upload-*')))

    def test_changed_same_version_and_rollback_rejected(self):
        data, metadata = self.artifact()
        self.put(data, metadata)
        changed, changed_meta = self.artifact(marker=b'different-code')
        self.assertEqual(self.put(changed, changed_meta).status_code, 409)
        older, older_meta = self.artifact(5)
        self.assertEqual(self.put(older, older_meta).status_code, 409)
        self.assertEqual(self.feed.apk.read_bytes(), data)

    def test_diagnostic_and_private_fixtures_rejected(self):
        data, metadata = self.artifact()
        metadata['diagnostic_only'] = True
        self.assertEqual(self.put(data, metadata).status_code, 400)
        for name, value in [('assets/replay/input.pcm', b'private-audio'),
                            ('assets/voice/vosk/settings.json', '{"diagnostic_only":true}'),
                            ('assets/voice/vosk/settings.json', '[]'),
                            ('assets/voice/vosk/settings.json', 'null')]:
            data, metadata = self.artifact(extra={name: value})
            self.assertEqual(self.put(data, metadata).status_code, 400)
        self.assertFalse(self.feed.apk.exists())

    def test_declared_size_and_invalid_zip_rejected(self):
        data, metadata = self.artifact()
        metadata['size'] += 1
        self.assertEqual(self.put(data, metadata).status_code, 400)
        data = b'not-an-apk'
        metadata.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual(self.put(data, metadata).status_code, 400)
        metadata['size'] = 65 * 1024 * 1024
        self.assertEqual(self.put(data, metadata).status_code, 400)

    def test_private_extra_metadata_rejected_before_writing(self):
        data, metadata = self.artifact()
        metadata['account_name'] = 'synthetic-private-owner'
        self.assertEqual(self.put(data, metadata).status_code, 400)
        self.assertFalse(self.feed.apk.exists())

    def test_retry_repairs_crash_between_file_and_metadata(self):
        old, old_meta = self.artifact(5)
        self.put(old, old_meta)
        new, new_meta = self.artifact(6, marker=b'new-release-code')
        import os
        real_replace = os.replace
        calls = []
        def replace(source, target):
            calls.append(str(target))
            if str(target).endswith('.release.json'):
                raise OSError('isolated crash')
            return real_replace(source, target)
        with patch('personal_assistant.relay.release_upload.os.replace', replace):
            with self.assertRaises(OSError):
                self.put(new, new_meta)
        with self.assertRaises(ValueError):
            self.feed.manifest()
        result = self.put(new, new_meta)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(self.feed.manifest()['version_code'], 6)
        self.assertEqual(self.feed.apk.read_bytes(), new)
