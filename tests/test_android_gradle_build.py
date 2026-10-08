"""Build boundaries: private inputs, reproducible payloads, persistent release identity."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


gradle = module('android_gradle_build')
builder = module('build_android_companion')


class AndroidBuildBoundaries(unittest.TestCase):
    def test_firebase_generated_resources_match_package_and_escape_values(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            config = folder / 'external.json'
            config.write_text(json.dumps({'project_info': {'project_number': '123', 'project_id': 'test-project'}, 'client': [
                {'client_info': {'android_client_info': {'package_name': 'com.personalassistant.companion'}, 'mobilesdk_app_id': '1:123:android:test'}, 'api_key': [{'current_key': 'public-test-key&value'}]}]}))
            output = folder / 'generated/values/firebase.xml'
            gradle.firebase_resources(config, output)
            strings = {node.attrib['name']: node.text for node in ET.parse(output).getroot()}
            self.assertEqual(strings['google_api_key'], 'public-test-key&value')
            self.assertEqual(strings['gcm_defaultSenderId'], '123')
            self.assertNotIn('client_email', output.read_text())
            wrong = json.loads(config.read_text())
            wrong['client'][0]['client_info']['android_client_info']['package_name'] = 'example.other'
            config.write_text(json.dumps(wrong))
            with self.assertRaises(ValueError):
                gradle.firebase_resources(config, output)

    def test_next_build_removes_previous_private_diagnostic_assets(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            fixture = folder / 'private-fixtures'
            fixture.mkdir()
            (fixture / 'input.pcm').write_bytes(b'private-test-pcm')
            work = folder / 'workspace'
            staged = gradle.stage_inputs(work, [], [], assets=fixture)
            self.assertTrue((staged / 'assets/input.pcm').is_file())
            generic = folder / 'generic-model'
            generic.write_bytes(b'generic-model')
            staged = gradle.stage_inputs(work, [], [(generic, 'assets/voice/model.bin')])
            self.assertFalse((staged / 'assets/input.pcm').exists())
            self.assertEqual((staged / 'assets/voice/model.bin').read_bytes(), b'generic-model')
            self.assertNotIn('package', ET.parse(staged / 'AndroidManifest.xml').getroot().attrib)

    def test_recompression_retains_extracted_hashes_and_uncompressed_native_table(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            source, target = folder / 'original.apk', folder / 'recompressed.apk'
            entries = {'assets/voice/model.bin': b'model' * 10000, 'lib/arm64-v8a/runtime.so': b'native' * 100, 'resources.arsc': b'table' * 100}
            with zipfile.ZipFile(source, 'w') as archive:
                for name, value in entries.items():
                    archive.writestr(name, value)
            builder.recompress_apk(source, target)
            with zipfile.ZipFile(target) as archive:
                for name, expected in entries.items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).digest(), hashlib.sha256(expected).digest())
                self.assertEqual(archive.getinfo('lib/arm64-v8a/runtime.so').compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.getinfo('resources.arsc').compress_type, zipfile.ZIP_STORED)
            self.assertLess(target.stat().st_size, source.stat().st_size)

    def test_ci_cannot_generate_a_new_release_signer(self):
        with tempfile.TemporaryDirectory() as raw, patch.dict('os.environ', {'CI': 'true'}), patch.object(builder.subprocess, 'run') as command:
            folder = Path(raw)
            with self.assertRaisesRegex(ValueError, 'existing signing key'):
                builder.build(folder / 'sdk', folder / 'output.apk', folder / 'signing')
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
