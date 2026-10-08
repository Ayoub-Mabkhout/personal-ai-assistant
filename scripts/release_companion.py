"""Verify trusted version tags and publish exactly one normal companion artifact.

Publication credentials are environment inputs. HTTPS redirects are forbidden;
an existing GitHub release can only be reused when both assets are byte-identical.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "com.personalassistant.companion"
MAX_APK_BYTES = 50 * 1024 * 1024
VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
ANDROID = "{http://schemas.android.com/apk/res/android}"
REQUIRED_ASSETS = {
    "assets/voice/vosk/settings.json", "assets/voice/licenses/Apache-2.0.txt",
    "assets/voice/licenses/vosk-upstream-COPYING.txt", "assets/voice/licenses/vosk-jna-NOTICE.txt",
}
RELEASE_FIELDS = {"package_name", "version_code", "version_name", "min_sdk", "size", "sha256",
                  "native_push_configured", "diagnostic_only", "contains_private_audio_fixture"}
DIAGNOSTIC_CLASSES = (b"ReplayVoiceService", b"VoskInstrumentation", b"VoskGainInstrumentation",
                      b"OpenWakeInstrumentation", b"UiInstrumentation", b"KeyguardInstrumentation",
                      b"ReplayInstrumentation", b"TaskUiInstrumentation")


def command(arguments, cwd=ROOT):
    result = subprocess.run([str(value) for value in arguments], cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        # CLI stderr and command arguments can contain private runtime inputs.
        raise ValueError("Release command failed: " + Path(str(arguments[0])).name)
    return result.stdout.strip()


def version_tag(value):
    if not VERSION.fullmatch(value):
        raise ValueError("Use a stable release tag such as v1.2.3.")
    return value[1:]


def source_version(manifest=ROOT / "apps/android/AndroidManifest.xml"):
    root = ET.parse(manifest).getroot()
    return {"package_name": root.attrib["package"], "version_code": int(root.attrib[ANDROID + "versionCode"]),
            "version_name": root.attrib[ANDROID + "versionName"]}


def verify_tag(event_path, ref, event_name, repository, expected_sha, root=ROOT):
    if event_name != "push" or not ref.startswith("refs/tags/"):
        raise ValueError("Only pushed stable version tags may release.")
    tag = ref[len("refs/tags/"):]
    version_tag(tag)
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    repo = event.get("repository", {})
    if event.get("deleted") or repo.get("fork") or repo.get("full_name") != repository:
        raise ValueError("Release tags must belong to the source repository.")
    default = repo.get("default_branch", "")
    if not default or command(["git", "check-ref-format", "refs/heads/" + default], cwd=root):
        raise ValueError("The repository default branch is invalid.")
    command(["git", "fetch", "--no-tags", "origin", "+refs/heads/" + default + ":refs/remotes/origin/" + default], cwd=root)
    commit = command(["git", "rev-parse", "refs/tags/" + tag + "^{commit}"], cwd=root)
    head = command(["git", "rev-parse", "HEAD"], cwd=root)
    if commit != head or commit != expected_sha:
        raise ValueError("Tag, event commit and checked-out source must match.")
    command(["git", "merge-base", "--is-ancestor", commit, "refs/remotes/origin/" + default], cwd=root)
    if source_version(root / "apps/android/AndroidManifest.xml")["version_name"] != version_tag(tag):
        raise ValueError("Tag and Android versionName must match.")
    return tag


def verify_artifact(apk, tag, manifest=ROOT / "apps/android/AndroidManifest.xml", aapt=None):
    apk = Path(apk)
    metadata = apk.with_suffix(".release.json")
    if apk.name != "assistant-companion.apk" or metadata.stat().st_size > 8192:
        raise ValueError("Use the normal companion APK and a small release manifest.")
    release = json.loads(metadata.read_text(encoding="utf-8"))
    if not isinstance(release, dict) or set(release) - RELEASE_FIELDS:
        raise ValueError("Unexpected release manifest fields cannot be published.")
    payload = apk.read_bytes()
    expected = source_version(manifest)
    if (release.get("package_name") != PACKAGE
            or any(release.get(key) != value for key, value in expected.items())
            or release.get("version_name") != version_tag(tag)
            or type(release.get("version_code")) is not int or release["version_code"] < 1
            or release.get("min_sdk") != 26
            or release.get("size") != len(payload) or not 0 < len(payload) <= MAX_APK_BYTES
            or release.get("sha256") != hashlib.sha256(payload).hexdigest()
            or release.get("diagnostic_only") or release.get("contains_private_audio_fixture")
            or release.get("native_push_configured") is not True):
        raise ValueError("Artifact metadata, version, normal runtime, push configuration or checksum is invalid.")
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or not REQUIRED_ASSETS.issubset(names):
            raise ValueError("APK entries or upstream notices are invalid.")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Unsafe APK entry.")
            if name.startswith("assets/") and not name.startswith(("assets/voice/vosk/model/", "assets/voice/licenses/")) and name != "assets/voice/vosk/settings.json":
                raise ValueError("Only the generic Vosk model and license assets may be released.")
            if path.suffix.lower() in {".pcm", ".wav", ".m4a", ".mp3", ".jks", ".keystore", ".p12", ".pem", ".key"}:
                raise ValueError("Private audio or credential material cannot be released.")
            if name.startswith("lib/") and not name.startswith("lib/arm64-v8a/"):
                raise ValueError("The normal release must contain only the ARM64 native runtime.")
            if name.endswith(".dex") and any(marker in archive.read(name) for marker in DIAGNOSTIC_CLASSES):
                raise ValueError("Diagnostic classes cannot be released.")
        settings = json.loads(archive.read("assets/voice/vosk/settings.json"))
        if settings.get("diagnostic_only") is not False or settings.get("diagnostic_no_activation") is not False:
            raise ValueError("Diagnostic wake settings cannot be released.")
        if not any(name.startswith("assets/voice/vosk/model/") for name in names) or not any(name.startswith("lib/arm64-v8a/") for name in names):
            raise ValueError("The normal release requires the generic model and ARM64 runtime.")
    if aapt:
        badging = command([aapt, "dump", "badging", apk])
        package = re.search(r"package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']+)'", badging)
        if not package or package.groups() != (PACKAGE, str(release["version_code"]), release["version_name"]):
            raise ValueError("APK manifest differs from the release metadata.")
        tree = command([aapt, "dump", "xmltree", apk, "AndroidManifest.xml"])
        if "application-debuggable" in badging or "E: instrumentation" in tree:
            raise ValueError("Debuggable or instrumentation APKs cannot be released.")
    return release


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def publish_https(apk, release, url, token):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != "/companion/v1/releases/artifact"):
        raise ValueError("Publication requires the configured HTTPS companion artifact endpoint.")
    if not token or any(character.isspace() for character in token):
        raise ValueError("A publication token is required.")
    manifest = json.dumps(release, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=Path(apk).read_bytes(), method="PUT", headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/vnd.android.package-archive",
        "X-Release-Manifest": base64.b64encode(manifest).decode("ascii"),
    })
    try:
        with urllib.request.build_opener(NoRedirects()).open(request, timeout=180) as response:
            receipt = json.loads(response.read(16385))
    except (urllib.error.URLError, ValueError, OSError):
        raise ValueError("HTTPS artifact publication failed; check the protected server receipt.") from None
    # The server's response never establishes handset delivery or installation.
    if (not isinstance(receipt, dict) or receipt.get("version_code") != release["version_code"]
            or receipt.get("sha256") != release["sha256"] or receipt.get("state") not in {"pending", "accepted"}):
        raise ValueError("Invalid publication receipt.")


def publish(apk, tag, repository):
    release = verify_artifact(apk, tag)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository.")
    apk = Path(apk).resolve()
    metadata = apk.with_suffix(".release.json")
    gh = ["gh", "release"]
    with tempfile.TemporaryDirectory(prefix="companion-release-") as directory:
        temporary = Path(directory)
        listed = json.loads(command([*gh, "list", "--repo", repository, "--limit", "1000", "--json", "tagName"]))
        if any(item.get("tagName") == tag for item in listed):
            for file in (apk, metadata):
                command([*gh, "download", tag, "--repo", repository, "--pattern", file.name, "--dir", temporary])
                if (temporary / file.name).read_bytes() != file.read_bytes():
                    raise ValueError("An existing release cannot be replaced with different bytes.")
        else:
            notes = temporary / "notes.md"
            notes.write_text("Signed ARM64 native companion. Install over the existing app to preserve its local data.\n\n"
                             "Wake detection remains experimental and disabled by default. Handset delivery, installation, "
                             "physical microphone and sustained lock-screen operation require device verification.\n\n"
                             "APK SHA-256: `" + release["sha256"] + "`\n", encoding="utf-8")
            command([*gh, "create", tag, apk, metadata, "--repo", repository, "--verify-tag", "--draft",
                     "--title", "Companion " + tag, "--notes-file", notes])
        publish_https(apk, release, os.environ.get("COMPANION_PUBLICATION_URL", ""), os.environ.get("COMPANION_PUBLICATION_TOKEN", ""))
        command([*gh, "edit", tag, "--repo", repository, "--draft=false", "--latest"])
    return {"version_name": release["version_name"], "sha256": release["sha256"], "published": True,
            "handset_delivery_verified": False}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="operation", required=True)
    commands.add_parser("verify-tag")
    for operation in ("verify", "publish"):
        command_cli = commands.add_parser(operation)
        command_cli.add_argument("--apk", required=True, type=Path)
        command_cli.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME", ""))
        if operation == "verify":
            command_cli.add_argument("--aapt", type=Path)
    args = cli.parse_args()
    try:
        if args.operation == "verify-tag":
            tag = verify_tag(os.environ["GITHUB_EVENT_PATH"], os.environ["GITHUB_REF"], os.environ["GITHUB_EVENT_NAME"],
                             os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"])
            result = {"tag": tag, "trusted": True}
        elif args.operation == "verify":
            release = verify_artifact(args.apk, args.tag, aapt=args.aapt)
            result = {"version_name": release["version_name"], "sha256": release["sha256"], "verified": True}
        else:
            result = publish(args.apk, args.tag, os.environ["GITHUB_REPOSITORY"])
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, ET.ParseError):
        # Avoid echoing deployment URLs, tokens, provider configs or CLI diagnostics.
        print("Companion release failed validation or publication. Review the failed workflow step and protected server receipt.", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
