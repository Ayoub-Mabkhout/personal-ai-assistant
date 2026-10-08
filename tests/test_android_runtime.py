"""Optional binary dependency manifest tampering must stop APK packaging."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/build_android_companion.py'
spec=importlib.util.spec_from_file_location('android_builder',SCRIPT)
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


class AndroidRuntimeTests(unittest.TestCase):
    def fixture(self,root):
        jar=root/'classes.jar';jar.write_bytes(b'isolated jar')
        binary=root/'runtime.so';binary.write_bytes(b'isolated runtime')
        data={'schema_version':1,'jars':[{'path':str(jar),'sha256':hashlib.sha256(jar.read_bytes()).hexdigest()}],
            'files':[{'path':str(binary),'entry':'lib/arm64-v8a/runtime.so','sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}]}
        manifest=root/'runtime.json';manifest.write_text(json.dumps(data))
        return manifest,data,binary

    def test_tampered_dependency_never_reaches_packager(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest,data,binary=self.fixture(Path(directory))
            jars,files=builder.runtime_dependencies(manifest)
            self.assertEqual(len(jars),1);self.assertEqual(files[0][1],'lib/arm64-v8a/runtime.so')
            binary.write_bytes(b'changed dependency')
            with self.assertRaises(ValueError):builder.runtime_dependencies(manifest)

    def test_manifest_cannot_inject_unrelated_or_traversing_apk_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest,data,binary=self.fixture(Path(directory))
            for invalid in ('AndroidManifest.xml','assets/voice/../../config.env','lib/arm64-v8a\\runtime.so'):
                data['files'][0]['entry']=invalid;manifest.write_text(json.dumps(data))
                with self.assertRaises(ValueError):builder.runtime_dependencies(manifest)
