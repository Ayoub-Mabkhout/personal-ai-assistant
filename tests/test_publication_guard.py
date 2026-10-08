"""Publication checks use isolated Git indexes and synthetic private values."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "publication_guard", Path(__file__).resolve().parents[1] / "scripts/check_publication.py")
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


def synthetic_key():
    # Assemble at runtime so no key-shaped literal is published by this test.
    return "sk-" + "aB9_" * 9


class ContentTests(unittest.TestCase):
    def rules(self, name, data, **kwargs):
        return {finding.rule for finding in guard.scan_blob(name, data, **kwargs)}

    def test_provider_literals_are_rejected_in_tests_and_templates(self):
        for name in ("src/app.py", "tests/fixture.py", ".env.example"):
            with self.subTest(name=name):
                self.assertIn("openai-key", self.rules(name, synthetic_key().encode()))

    def test_generated_keys_and_reserved_examples_are_allowed(self):
        source = b"key = secrets.token_bytes(32)\nemail = 'owner@example.com'\n"
        self.assertFalse(self.rules("tests/generic.py", source))
        for domain in ("example.org", "sub.example.net", "example.test", "example.invalid", "example.example"):
            self.assertFalse(self.rules("template.md", ("owner@" + domain).encode()))

    def test_other_provider_shapes_are_rejected(self):
        values = (
            ("ghp_" + "aB9" * 12, "github-token"),
            ("AK" + "IA" + "A1" * 8, "aws-access-key"),
            ("AI" + "za" + "aB9_" * 8 + "xyz", "google-api-key"),
            ("xoxb-" + "1234567890-" * 3, "slack-token"),
            ("sk_live_" + "aB9" * 9, "stripe-key"),
            ("ya29." + "aB9_" * 8, "google-oauth-token"),
            ("AccountKey=" + "aB9/" * 12 + "==", "azure-storage-key"),
            ("eyJ" + "abc123" * 3 + "." + "abc123" * 4 + "." + "abc123" * 4, "jwt-literal"),
        )
        for value, rule in values:
            with self.subTest(rule=rule):
                self.assertIn(rule, self.rules("tests/fixture.txt", value.encode()))

    def test_quoted_and_environment_credentials_are_rejected(self):
        secret = "aB9cD8eF7gH6" + "iJ5kL4mN3pQ2"
        self.assertIn("credential-literal", self.rules("config.py", ("worker_token='" + secret + "'").encode()))
        self.assertIn("credential-literal", self.rules(".env.example", ("PROVIDER_API_KEY=" + secret).encode()))
        self.assertFalse(self.rules(".env.example", b"PROVIDER_API_KEY=REPLACE_WITH_PROVIDER_API_KEY\n"))

    def test_nonexample_email_and_home_paths_report_locations_only(self):
        address = "person@" + "mail-provider.com"
        home = "C:" + "/Users/" + "SyntheticOwner" + "/documents"
        text = "safe\n" + address + "\n" + home
        findings = guard.scan_blob("source.md", text.encode())
        self.assertEqual([(item.line, item.rule) for item in sorted(findings)],
                         [(2, "nonexample-email"), (3, "owner-home-path")])
        serialized = json.dumps([guard.asdict(item) for item in findings])
        self.assertNotIn(address, serialized)
        self.assertNotIn(home, serialized)

    def test_generic_home_examples_and_service_paths_are_allowed(self):
        text = "C:" + "/Users/you/project\n/opt/personal-assistant\n/home/assistant/runtime"
        self.assertFalse(self.rules("instructions.md", text.encode()))

    def test_escaped_windows_home_and_utf16_are_checked(self):
        home = "C:" + "\\\\Users\\\\" + "SyntheticOwner" + "\\\\project"
        self.assertIn("owner-home-path", self.rules("config.py", home.encode()))
        self.assertIn("openai-key", self.rules("text.txt", synthetic_key().encode("utf-16")))

    def test_binary_secret_and_unknown_binary_fail_closed(self):
        blob = b"\x00\xff" + synthetic_key().encode() + b"\x00"
        self.assertEqual(self.rules("payload.bin", blob), {"openai-key", "unsupported-binary"})
        self.assertIn("unsupported-binary", self.rules("payload.bin", b"\x00\xff"))

    def test_source_images_do_not_hide_ascii_credentials(self):
        image = b"\x89PNG\r\n\x1a\n\x00\xff"
        self.assertFalse(self.rules("icon.png", image))
        self.assertIn("openai-key", self.rules("icon.png", image + synthetic_key().encode()))

    def test_jar_members_are_checked(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr("org/example/Class.class", b"\xca\xfe\xba\xbe" + synthetic_key().encode())
            archive.writestr("credentials.json", "{}")
        findings = guard.scan_blob("wrapper.jar", content.getvalue())
        self.assertIn("openai-key", {finding.rule for finding in findings})
        self.assertIn("credential-file", {finding.rule for finding in findings})
        self.assertTrue(any("!/" in finding.file for finding in findings))

    def test_private_paths_and_artifacts_are_rejected(self):
        for name in ("private/profile.md", "state/result.json", "config/local/worker.json",
                     "data/archive.json", "nested/.env.production", "nested/signing.jks",
                     "nested/service-account-project.json", ".aws/credentials", "debug.apk",
                     "voice.pcm", "record.sqlite3", "nested/google-services.json"):
            with self.subTest(name=name):
                self.assertTrue(guard.path_rule(name))
        for name in (".env.example", "infra/server/.env.example", "config/templates/accounts.json",
                     "src/personal_assistant/profile.py", "docs/calendar.md"):
            with self.subTest(name=name):
                self.assertIsNone(guard.path_rule(name))

    def test_optional_identifiers_are_checked_without_echoing_values(self):
        identifier = "Synthetic" + "OwnerIdentifier"
        findings = guard.scan_blob("note.md", ("safe\n" + identifier.lower()).encode(), [identifier])
        self.assertEqual(findings, {guard.Finding("note.md", 2, "configured-private-identifier")})

    def test_private_key_header_is_rejected(self):
        header = "-----BEGIN " + "PRIVATE KEY-----"
        self.assertIn("private-key", self.rules("source.txt", header.encode()))

    def test_oversized_blob_fails_closed(self):
        with mock.patch.object(guard, "MAX_FILE_BYTES", 4):
            self.assertEqual(self.rules("large.txt", b"12345"), {"file-too-large"})


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        guard.git(self.root, "init", "-q")
        self.write(".gitignore", "state/\nprivate/\nconfig/local/\n")
        self.add(".gitignore")

    def write(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents if isinstance(contents, bytes) else contents.encode())

    def add(self, *names, force=False):
        guard.git(self.root, "add", *(["-f"] if force else []), "--", *names)

    def commit(self):
        guard.git(self.root, "-c", "user.name=Test Fixture", "-c", "user.email=fixture@example.test",
                  "-c", "commit.gpgsign=false", "commit", "-qm", "isolated fixture")

    def scan(self, **kwargs):
        return guard.scan_repository(self.root, **kwargs)[1]

    def test_ignored_private_and_untracked_files_are_outside_index(self):
        self.write("state/result.json", synthetic_key())
        self.write("private/profile.md", "Synthetic owner")
        self.write("draft.py", synthetic_key())
        self.assertFalse(self.scan())
        preview = self.scan(include_untracked=True)
        self.assertEqual(preview, [guard.Finding("draft.py", 1, "openai-key")])

    def test_force_added_private_path_is_rejected(self):
        self.write("state/result.json", "private")
        self.add("state/result.json", force=True)
        self.assertEqual(self.scan(), [guard.Finding("state/result.json", 1, "private-path")])

    def test_index_blob_is_checked_even_if_worktree_was_cleaned(self):
        self.write("app.py", synthetic_key())
        self.add("app.py")
        self.write("app.py", "key = os.environ['API_KEY']")
        self.assertEqual(self.scan(), [guard.Finding("app.py", 1, "openai-key")])

    def test_unstaged_worktree_does_not_change_commit_check(self):
        self.write("app.py", "key = os.environ['API_KEY']")
        self.add("app.py")
        self.write("app.py", synthetic_key())
        self.assertFalse(self.scan())

    def test_staged_selection_and_deleted_files(self):
        self.write("old.py", synthetic_key())
        self.add("old.py")
        self.commit()
        self.write("new.py", "safe")
        self.add("new.py")
        self.assertFalse(self.scan(staged=True))
        self.assertTrue(self.scan())
        guard.git(self.root, "rm", "-q", "old.py")
        self.assertFalse(self.scan(staged=True))
        self.assertFalse(self.scan())

    def test_staged_binary_content_is_scanned(self):
        self.write("payload.bin", b"\x00" + synthetic_key().encode() + b"\xff")
        self.add("payload.bin")
        self.assertEqual({finding.rule for finding in self.scan(staged=True)},
                         {"openai-key", "unsupported-binary"})

    def test_identifier_configuration_must_be_ignored_or_external(self):
        values = {"identifiers": ["SyntheticOwnerIdentifier"]}
        self.write("config/local/publication-identifiers.json", json.dumps(values))
        config = self.root / "config/local/publication-identifiers.json"
        self.assertEqual(guard.load_identifiers(self.root, config), tuple(values["identifiers"]))
        self.write("identifiers.json", json.dumps(values))
        with self.assertRaises(guard.GuardError):
            guard.load_identifiers(self.root, self.root / "identifiers.json")
        self.add("config/local/publication-identifiers.json", force=True)
        with self.assertRaises(guard.GuardError):
            guard.load_identifiers(self.root, config)

    def test_invalid_identifier_config_and_repository_errors_fail_closed(self):
        self.write("config/local/bad.json", "{\"identifiers\": []}")
        with self.assertRaises(guard.GuardError):
            guard.load_identifiers(self.root, self.root / "config/local/bad.json")
        with mock.patch.object(guard, "ROOT", self.root), mock.patch.object(
                guard, "scan_repository", side_effect=guard.GuardError("git-operation-failed")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(guard.main([]), 1)
            report = json.loads(output.getvalue())
            self.assertFalse(report["ok"])
            self.assertEqual(report["errors"], ["git-operation-failed"])


if __name__ == "__main__":
    unittest.main()
