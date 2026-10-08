"""Create a Home Assistant owner through its private loopback onboarding API.

Run as root on the server. Credentials remain in a private file outside the
source tree. The proxy must still be using Caddyfile.bootstrap.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import urllib.parse
import urllib.request

if __package__:
    from .prepare_server import ROOT, write_new
else:
    from prepare_server import ROOT, write_new

BASE = 'http://127.0.0.1:8123'
CLIENT = BASE + '/'


def request(path, payload=None, token=None, form=False):
    headers = {}
    body = None
    if payload is not None:
        body = (urllib.parse.urlencode(payload) if form else json.dumps(payload)).encode()
        headers['Content-Type'] = ('application/x-www-form-urlencoded' if form else 'application/json')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(BASE + path, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def onboard(directory, name, username='assistant'):
    directory = Path(directory).resolve()
    if directory.is_relative_to(ROOT):
        raise ValueError('Owner credentials must stay outside the source tree.')
    if os.name != 'posix' or os.geteuid() != 0:
        raise ValueError('Run on the Linux server as root.')
    if not (directory / '.env').is_file():
        raise ValueError('Run prepare_server.py first.')
    if not (directory / 'secrets').is_dir():
        raise ValueError('Prepared private credential directory is missing.')
    (directory / 'secrets').chmod(0o700)
    credential_path = directory / 'secrets/homeassistant-owner.json'
    steps = request('/api/onboarding')
    completed = {step['step'] for step in steps if step['done']}
    if credential_path.exists():
        credentials = json.loads(credential_path.read_text(encoding='utf-8'))
    else:
        if 'user' in completed:
            raise ValueError('An owner already exists. Refusing to replace it.')
        credentials = {'username': username, 'password': secrets.token_urlsafe(24)}
        write_new(credential_path, json.dumps(credentials) + '\n')
    credential_path.chmod(0o600)
    if 'user' not in completed:
        created = request('/api/onboarding/users', {
            'name': name, 'username': credentials['username'],
            'password': credentials['password'], 'client_id': CLIENT, 'language': 'en',
        })
        tokens = request('/auth/token', {
            'grant_type': 'authorization_code', 'code': created['auth_code'],
            'client_id': CLIENT,
        }, form=True)
        credentials['refresh_token'] = tokens['refresh_token']
        credential_path.write_text(json.dumps(credentials) + '\n', encoding='utf-8')
    else:
        if 'refresh_token' not in credentials:
            raise ValueError('Owner exists but setup token was not saved. Recover login before continuing.')
        tokens = request('/auth/token', {
            'grant_type': 'refresh_token', 'refresh_token': credentials['refresh_token'],
            'client_id': CLIENT,
        }, form=True)
    token = tokens['access_token']
    if 'core_config' not in completed:
        request('/api/onboarding/core_config', {}, token)
    if 'analytics' not in completed:
        request('/api/onboarding/analytics', {}, token)
    if 'integration' not in completed:
        request('/api/onboarding/integration', {
            'client_id': CLIENT, 'redirect_uri': CLIENT + '?auth_callback=1',
        }, token)
    request('/api/', token=token)
    return {'owner_created_or_verified': True, 'credentials_file': str(credential_path),
            'credentials_printed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('/opt/personal-assistant'))
    parser.add_argument('--name', required=True)
    parser.add_argument('--username', default='assistant')
    args = parser.parse_args()
    print(json.dumps(onboard(args.directory, args.name, args.username)))
