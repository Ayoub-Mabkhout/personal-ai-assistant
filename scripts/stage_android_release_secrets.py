"""Stage release inputs only in the hosted runner's temporary directory."""
import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import shutil
import sys

DIRECTORY = "personal-assistant-release-secrets"


def staging_directory():
    value = os.environ.get("RUNNER_TEMP")
    if not value:
        raise ValueError("RUNNER_TEMP is required for release secret staging.")
    parent = Path(value).resolve(strict=True)
    directory = parent / DIRECTORY
    if directory.is_symlink() or directory.resolve().parent != parent:
        raise ValueError("Release staging must stay inside RUNNER_TEMP.")
    return directory


def decode(name):
    try:
        result = base64.b64decode(os.environ.get(name, ""), validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid release secret: " + name) from None
    if not result:
        raise ValueError("Missing release secret: " + name)
    return result


def stage():
    directory = staging_directory()
    key = decode("ANDROID_SIGNING_KEY_BASE64")
    password = os.environ.get("ANDROID_SIGNING_PASSWORD", "")
    if not password or any(character in password for character in "\r\n\0"):
        raise ValueError("A nonempty single-line signing password is required.")
    firebase = decode("FIREBASE_ANDROID_CONFIG_BASE64")
    try:
        config = json.loads(firebase.decode("utf-8-sig"))
        clients = config["client"]
        packages = [client["client_info"]["android_client_info"]["package_name"] for client in clients]
    except (ValueError, KeyError, TypeError):
        raise ValueError("Firebase input must be an Android client configuration.") from None
    if "com.personalassistant.companion" not in packages or "private_key" in config:
        raise ValueError("Firebase input must configure the companion client, without a service-account key.")
    directory.mkdir(mode=0o700, exist_ok=False)
    try:
        signing = directory / "signing"
        signing.mkdir(mode=0o700)
        for path, content in ((signing / "companion.p12", key),
                              (signing / "password.txt", password.encode("utf-8")),
                              (directory / "google-services.json", firebase)):
            path.write_bytes(content)
            path.chmod(0o600)
    except Exception:
        cleanup()
        raise


def cleanup():
    directory = staging_directory()
    if directory.exists():
        shutil.rmtree(directory)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--cleanup", action="store_true")
    args = cli.parse_args()
    try:
        cleanup() if args.cleanup else stage()
    except (ValueError, OSError) as error:
        # Never print decoded values, provider JSON, or passwords.
        print("Release input staging failed: " + (str(error) if isinstance(error, ValueError) else "file operation failed"), file=sys.stderr)
        return 1
    print("Release inputs removed." if args.cleanup else "Release inputs staged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
