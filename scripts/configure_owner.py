"""Initialize standalone login from a protected credential file or interactive input."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from personal_assistant.relay.owner_credentials import password_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--credentials-file', type=Path, help='Protected JSON with username and password; never copied into output.')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Owner already configured; preserve existing login.')
    value = json.loads(args.credentials_file.read_text(encoding='utf-8-sig')) if args.credentials_file else {'username': input('Username: '), 'password': getpass.getpass()}
    record = password_record(value['username'], value['password'])
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(record, stream)
    if os.name == 'posix': os.chown(args.output, 10001, 10001)
    print('Owner configured; no credentials printed.')


if __name__ == '__main__': main()
