"""Read-only Enable Banking client (PSD2 account information). It never initiates payments.

The application description is a runtime file holding the application id, the redirect URL
and the private key file name, kept in a protected directory outside the repository.
"""
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.enablebanking.com'


class ProviderError(RuntimeError):
    def __init__(self, status, detail):
        super().__init__('Enable Banking %s: %s' % (status, detail))
        self.status, self.detail = status, detail


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=')


class EnableBanking:
    def __init__(self, application_file, api=API, opener=None, clock=time.time):
        self.file = Path(application_file)
        meta = json.loads(self.file.read_text(encoding='utf-8'))
        self.application_id, self.redirect_url = meta['application_id'], meta['redirect_url']
        self.key_file = self.file.parent / meta['private_key']
        self.api, self.clock = api.rstrip('/'), clock
        self.opener = opener or urllib.request.build_opener()
        self._key = None

    def token(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        if self._key is None:
            self._key = serialization.load_pem_private_key(self.key_file.read_bytes(), None)
        now = int(self.clock())
        head = b64(json.dumps({'typ': 'JWT', 'alg': 'RS256', 'kid': self.application_id}).encode())
        body = b64(json.dumps({'iss': 'enablebanking.com', 'aud': 'api.enablebanking.com', 'iat': now, 'exp': now + 600}).encode())
        return (head + b'.' + body + b'.' + b64(self._key.sign(head + b'.' + body, padding.PKCS1v15(), hashes.SHA256()))).decode()

    def call(self, method, path, payload=None, query=None):
        url = self.api + path + ('?' + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None}) if query else '')
        request = urllib.request.Request(url, method=method, data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + self.token(), 'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')[:500]
            raise ProviderError(error.code, detail) from None

    def application(self):
        return self.call('GET', '/application')

    def banks(self, country):
        return self.call('GET', '/aspsps', query={'country': country})['aspsps']

    def start(self, bank, country, state, days=180):
        """Returns the bank login URL for a new consent of at most `days`."""
        until = datetime.now(timezone.utc) + timedelta(days=days)
        return self.call('POST', '/auth', {'access': {'valid_until': until.isoformat(timespec='seconds')},
            'aspsp': {'name': bank, 'country': country}, 'state': state, 'redirect_url': self.redirect_url, 'psu_type': 'personal'})

    def session(self, code):
        return self.call('POST', '/sessions', {'code': code})

    def session_status(self, session_id):
        return self.call('GET', '/sessions/' + urllib.parse.quote(session_id, safe=''))

    def balances(self, account):
        return self.call('GET', '/accounts/%s/balances' % urllib.parse.quote(account, safe=''))['balances']

    def transactions(self, account, date_from, limit_pages=50):
        items, key = [], None
        for _ in range(limit_pages):
            page = self.call('GET', '/accounts/%s/transactions' % urllib.parse.quote(account, safe=''),
                             query={'date_from': date_from, 'continuation_key': key})
            items += page.get('transactions') or []
            key = page.get('continuation_key')
            if not key:
                break
        return items
