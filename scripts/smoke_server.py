"""Check public HTTPS routing after deployment; makes no authenticated changes."""

import argparse
import json
from urllib.parse import urlsplit
from urllib.request import urlopen


def check(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Use an HTTPS server origin without credentials, path or query.')
    base = url.rstrip('/')
    with urlopen(base + '/', timeout=20) as response:
        frontend = response.read(1000000).decode('utf-8')
        if response.status != 200 or 'Shopping' not in frontend and 'shopping' not in frontend:
            raise ValueError('Assistant frontend did not respond successfully.')
    with urlopen(base + '/relay/healthz', timeout=20) as response:
        if response.status != 200 or json.load(response).get('ok') is not True:
            raise ValueError('Relay health check failed.')
    return {'https': True, 'assistant_frontend': True, 'relay': True,
            'phone_url': base, 'voice_and_login_tested': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.url), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, 'Server check failed: ' + str(exc) + '\n')
