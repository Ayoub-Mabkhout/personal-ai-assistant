"""Release boundary tests use temporary fake APKs, keys and HTTP transports."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_script("release_companion")
staging = load_script("stage_android_release_secrets")


class ReleaseAutomationTests(unittest.TestCase):
    def artifact(self, directory, extra=None, settings=None, dex=b"generic production classes"):
        root = Path(directory)
        apk = root / "assistant-companion.apk"
        manifest = root / "AndroidManifest.xml"
        manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
                            'package="com.personalassistant.companion" android:versionCode="6" '
                            'android:versionName="0.6.0"/>')
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"fake binary manifest")
            archive.writestr("classes.dex", dex)
            for name in release.REQUIRED_ASSETS - {"assets/voice/vosk/settings.json"}:
                archive.writestr(name, b"generic license fixture")
            archive.writestr("assets/voice/vosk/settings.json", json.dumps(settings or {
                "diagnostic_only": False, "diagnostic_no_activation": False}))
            archive.writestr("assets/voice/vosk/model/am/final.mdl", b"fake model")
            archive.writestr("lib/arm64-v8a/libvosk.so", b"fake native runtime")
            for name, content in (extra or {}).items():
                archive.writestr(name, content)
        metadata = {"package_name": release.PACKAGE, "version_code": 6, "version_name": "0.6.0", "min_sdk": 26,
                    "size": apk.stat().st_size, "sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
                    "native_push_configured": True}
        apk.with_suffix(".release.json").write_text(json.dumps(metadata))
        return apk, manifest, metadata

    def test_normal_artifact_and_version_require_exact_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            apk, manifest, metadata = self.artifact(directory)
            self.assertEqual(release.verify_artifact(apk, "v0.6.0", manifest), metadata)
            with self.assertRaises(ValueError):
                release.verify_artifact(apk, "v0.7.0", manifest)
            apk.write_bytes(apk.read_bytes() + b"changed")
            with self.assertRaises(ValueError):
                release.verify_artifact(apk, "v0.6.0", manifest)

    def test_diagnostics_private_audio_foreign_abi_and_unexpected_assets_fail(self):
        cases = [({"assets/replay/input.pcm": b"synthetic"}, None, b"production"),
                 ({"lib/x86_64/libvosk.so": b"fake"}, None, b"production"),
                 ({"assets/other.json": b"{}"}, None, b"production"),
                 ({}, {"diagnostic_only": True, "diagnostic_no_activation": True}, b"production"),
                 ({}, None, b"Lcom/personalassistant/companion/ReplayVoiceService;")]
        for extra, settings, dex in cases:
            with self.subTest(extra=list(extra), settings=settings), tempfile.TemporaryDirectory() as directory:
                apk, manifest, _ = self.artifact(directory, extra, settings, dex)
                with self.assertRaises(ValueError):
                    release.verify_artifact(apk, "v0.6.0", manifest)

    def test_manifest_cannot_hide_diagnostics_or_arbitrary_metadata(self):
        for change in ({"diagnostic_only": True}, {"contains_private_audio_fixture": True},
                       {"native_push_configured": False}, {"unreviewed_field": "private value"}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                apk, manifest, metadata = self.artifact(directory)
                apk.with_suffix(".release.json").write_text(json.dumps({**metadata, **change}))
                with self.assertRaises(ValueError):
                    release.verify_artifact(apk, "v0.6.0", manifest)

    def test_official_sdk_manifest_verification_blocks_instrumentation(self):
        with tempfile.TemporaryDirectory() as directory:
            apk, manifest, _ = self.artifact(directory)
            badging = "package: name='com.personalassistant.companion' versionCode='6' versionName='0.6.0'"
            with patch.object(release, "command", side_effect=[badging, "E: instrumentation (line=4)"]):
                with self.assertRaises(ValueError):
                    release.verify_artifact(apk, "v0.6.0", manifest, aapt="fake-sdk-aapt")

    def test_https_contract_transmits_exact_bytes_and_manifest_without_redirects(self):
        with tempfile.TemporaryDirectory() as directory:
            apk, _, metadata = self.artifact(directory)
            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self, limit): return json.dumps({"version_code": 6, "sha256": metadata["sha256"], "state": "pending"}).encode()
            captured = []
            class Transport:
                def open(self, request, timeout):
                    captured.append(request)
                    return Response()
            with patch.object(urllib.request, "build_opener", return_value=Transport()) as opener:
                release.publish_https(apk, metadata, "https://example.invalid/companion/v1/releases/artifact", "test-publish-token")
            request = captured[0]
            self.assertEqual(request.get_method(), "PUT")
            self.assertEqual(request.data, apk.read_bytes())
            self.assertEqual(json.loads(base64.b64decode(request.get_header("X-release-manifest"))), metadata)
            self.assertEqual(request.get_header("Authorization"), "Bearer test-publish-token")
            self.assertIsInstance(opener.call_args.args[0], release.NoRedirects)
            self.assertIsNone(release.NoRedirects().redirect_request(request, None, 302, "redirect", {}, "https://other.invalid/"))

    def test_publication_credential_cannot_go_to_other_paths_or_cleartext(self):
        for url in ("http://example.invalid/companion/v1/releases/artifact", "https://example.invalid/other",
                    "https://example.invalid/companion/v1/releases/artifact?token=hidden",
                    "https://user:password@example.invalid/companion/v1/releases/artifact"):
            with self.subTest(url=url), patch.object(urllib.request, "build_opener") as opener:
                with self.assertRaises(ValueError):
                    release.publish_https("not-read.apk", {}, url, "test-token")
                opener.assert_not_called()

    def test_release_tag_requires_push_and_source_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            event.write_text(json.dumps({"repository": {"fork": True, "full_name": "generic/repo", "default_branch": "master"}}))
            with patch.object(release, "command") as git:
                with self.assertRaises(ValueError):
                    release.verify_tag(event, "refs/tags/v0.6.0", "push", "generic/repo", "abc")
                git.assert_not_called()
            with self.assertRaises(ValueError):
                release.verify_tag(event, "refs/tags/v0.6.0", "pull_request", "generic/repo", "abc")
            with self.assertRaises(ValueError):
                release.version_tag("v0.6.0-rc1")

    def test_tag_ancestry_is_checked_before_any_secret_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "apps/android/AndroidManifest.xml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.personalassistant.companion" android:versionCode="6" android:versionName="0.6.0"/>')
            event = root / "event.json"
            event.write_text(json.dumps({"repository": {"fork": False, "full_name": "generic/repo", "default_branch": "master"}}))
            calls = []
            def fake_git(arguments, cwd):
                calls.append(arguments)
                if "rev-parse" in arguments: return "abc"
                if "merge-base" in arguments: raise ValueError("not an ancestor")
                return ""
            with patch.object(release, "command", side_effect=fake_git):
                with self.assertRaises(ValueError):
                    release.verify_tag(event, "refs/tags/v0.6.0", "push", "generic/repo", "abc", root)
            self.assertEqual(calls[-1], ["git", "merge-base", "--is-ancestor", "abc", "refs/remotes/origin/master"])

    def test_existing_github_release_bytes_cannot_be_clobbered(self):
        with tempfile.TemporaryDirectory() as directory:
            apk, manifest, _ = self.artifact(directory)
            def gh(arguments, cwd=release.ROOT):
                if "list" in arguments: return '[{"tagName":"v0.6.0"}]'
                if "download" in arguments:
                    destination = Path(arguments[arguments.index("--dir") + 1])
                    name = arguments[arguments.index("--pattern") + 1]
                    (destination / name).write_bytes(b"different existing release bytes")
                    return ""
                self.fail("Release mutation must not run after a mismatch")
            with patch.object(release, "source_version", return_value=release.source_version(manifest)), patch.object(release, "command", side_effect=gh), patch.object(release, "publish_https") as http:
                with self.assertRaises(ValueError):
                    release.publish(apk, "v0.6.0", "generic/repo")
                http.assert_not_called()


class ReleaseSecretStagingTests(unittest.TestCase):
    def env(self, root):
        config = {"client": [{"client_info": {"android_client_info": {"package_name": release.PACKAGE}}}]}
        return {"RUNNER_TEMP": str(root), "ANDROID_SIGNING_KEY_BASE64": base64.b64encode(b"synthetic key fixture").decode(),
                "ANDROID_SIGNING_PASSWORD": "synthetic test password", "FIREBASE_ANDROID_CONFIG_BASE64": base64.b64encode(json.dumps(config).encode()).decode()}

    def test_inputs_are_staged_only_in_runner_temp_and_removed(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, self.env(directory), clear=True):
            staging.stage()
            root = staging.staging_directory()
            self.assertEqual((root / "signing/companion.p12").read_bytes(), b"synthetic key fixture")
            self.assertEqual((root / "signing/password.txt").read_text(), "synthetic test password")
            staging.cleanup()
            self.assertFalse(root.exists())

    def test_missing_existing_key_and_multiline_password_fail_before_files(self):
        for change in ({"ANDROID_SIGNING_KEY_BASE64": ""}, {"ANDROID_SIGNING_PASSWORD": "secret\nsecond line"}):
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {**self.env(directory), **change}, clear=True):
                with self.assertRaises(ValueError):
                    staging.stage()
                self.assertFalse(staging.staging_directory().exists())

    def test_staging_cannot_follow_symlink_outside_runner_temp(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside, patch.dict(os.environ, self.env(directory), clear=True):
            target = Path(directory) / staging.DIRECTORY
            try:
                target.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation needs privileges on this Windows host")
            with self.assertRaises(ValueError):
                staging.cleanup()
            self.assertTrue(Path(outside).exists())
