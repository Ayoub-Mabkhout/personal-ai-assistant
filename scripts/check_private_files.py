"""Fail if private paths or non-template environment/credential files enter Git."""

import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {'private', 'state', 'data', 'secrets', '.venv', '.tools'}
CREDENTIAL_EXTENSIONS = {'.pem', '.key', '.p12', '.pfx'}


def main():
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True)
    rejected = []
    for name in result.stdout.decode('utf-8').split('\0'):
        if not name:
            continue
        path = PurePosixPath(name)
        env_file = path.name == '.env' or (path.name.startswith('.env.') and path.name != '.env.example')
        if (path.parts[0] in PRIVATE or name.startswith('config/local/') or env_file
                or path.suffix.lower() in CREDENTIAL_EXTENSIONS):
            rejected.append(name)
    print(json.dumps({'private_paths_in_git': rejected, 'ok': not rejected}, indent=2))
    # This checks paths only; it is not a secret scanner for arbitrary file contents.
    return int(bool(rejected))


if __name__ == '__main__':
    sys.exit(main())
