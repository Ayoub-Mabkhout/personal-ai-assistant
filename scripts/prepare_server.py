"""Prepare private Linux-host files, then enable public access after owner setup."""

import argparse
import json
import os
import re
import secrets
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def write_new(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    return True


def prepare(directory, domain, email, timezone_name='Europe/Berlin'):
    directory = Path(directory).resolve()
    if directory.is_relative_to(ROOT):
        raise ValueError('Server credentials/runtime must be outside the repository and OneDrive checkout.')
    domain = domain.lower()
    if len(domain) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain):
        raise ValueError('Use a DNS hostname without scheme, port, path or wildcard.')
    if not re.fullmatch(r'[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,63}', email):
        raise ValueError('Use a certificate contact email address.')
    ZoneInfo(timezone_name)
    if any(c in directory.as_posix() for c in '\n\r$# '):
        raise ValueError('Server directory must not contain spaces or environment-file metacharacters.')
    if os.name == 'posix' and os.geteuid() != 0:
        raise ValueError('Run initial server preparation with sudo to set container file ownership.')
    existing_env = directory / '.env'
    if existing_env.exists() and f'ASSISTANT_DOMAIN={domain}\n' not in existing_env.read_text(encoding='utf-8'):
        raise ValueError('Existing server uses another domain. Review its configuration before changing it.')
    secret_dir = directory / 'secrets'
    data_dir = directory / 'data'
    relay_dir = data_dir / 'relay'
    for path in (directory, secret_dir, relay_dir):
        path.mkdir(parents=True, exist_ok=True)
    if os.name == 'posix':
        secret_dir.chmod(0o700)
        os.chown(relay_dir, 10001, 10001)
        relay_dir.chmod(0o700)
    for name in ('submit_token', 'worker_token', 'groceries_token'):
        path = secret_dir / name
        write_new(path, secrets.token_urlsafe(48) + '\n', mode=0o440)
        if os.name == 'posix':
            os.chown(path, 0, 10001)
            path.chmod(0o440)
    submit_token = (secret_dir / 'submit_token').read_text(encoding='utf-8').strip()
    worker_token = (secret_dir / 'worker_token').read_text(encoding='utf-8').strip()
    if min(len(submit_token), len(worker_token)) < 32 or submit_token == worker_token:
        raise ValueError('Invalid existing service credentials; repair them before deployment.')
    settings = {'ASSISTANT_DOMAIN': domain, 'ACME_EMAIL': email,
                'ASSISTANT_TIMEZONE': timezone_name,
                'ASSISTANT_DATA_DIR': data_dir.as_posix(),
                'ASSISTANT_SECRET_DIR': secret_dir.as_posix(),
                'ASSISTANT_CADDY_CONFIG': 'Caddyfile.bootstrap'}
    write_new(existing_env, ''.join(f'{key}={value}\n' for key, value in settings.items()))
    return {'prepared': True, 'environment_file': str(existing_env),
            'public_access': 'disabled until owner setup', 'credentials_printed': False}


def publish(directory):
    directory = Path(directory).resolve()
    auth = directory / 'data/relay/owner-login.json'
    if not auth.is_file(): raise ValueError('Configure standalone owner login before publishing.')
    record=json.loads(auth.read_text())
    if not record.get('username') or len(record.get('password_hash',''))!=128 or len(record.get('salt',''))!=32:
        raise ValueError('Invalid standalone owner login; public access stays disabled.')
    env_path = directory / '.env'
    lines = env_path.read_text(encoding='utf-8').splitlines()
    if not any(line.startswith('ASSISTANT_CADDY_CONFIG=') for line in lines):
        raise ValueError('Server environment has no proxy configuration field.')
    replaced = ['ASSISTANT_CADDY_CONFIG=Caddyfile' if line.startswith('ASSISTANT_CADDY_CONFIG=') else line for line in lines]
    temporary = env_path.with_name('.env.new')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(replaced) + '\n')
    if os.name == 'posix':
        temporary.chmod(0o600)
    temporary.replace(env_path)
    return {'owner_verified': True, 'proxy_configuration': 'Caddyfile',
            'next': 'Recreate the proxy container to apply public access.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--directory', type=Path, default=Path('/opt/personal-assistant'))
    init.add_argument('--domain', required=True)
    init.add_argument('--email', required=True)
    init.add_argument('--timezone', default='Europe/Berlin')
    enable = commands.add_parser('publish')
    enable.add_argument('--directory', type=Path, default=Path('/opt/personal-assistant'))
    args = parser.parse_args()
    try:
        result = (prepare(args.directory, args.domain, args.email, args.timezone)
                  if args.command == 'init' else publish(args.directory))
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
