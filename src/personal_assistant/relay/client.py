"""Headless owner API client using protected file references; redirects are rejected."""
import json
from pathlib import Path
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


class OwnerClient:
    def __init__(self, config):
        self.base = config['relay_url'].rstrip('/')
        origin = urllib.parse.urlsplit(self.base)
        if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ('', '/relay'):
            raise ValueError('Use the relay HTTPS origin or /relay URL.')
        self.origin = urllib.parse.urlunsplit((origin.scheme, origin.netloc, '', '', ''))
        self.token_file = Path(config['submit_token_file'])
        self.opener = urllib.request.build_opener(NoRedirect)

    def call(self, path, payload=None):
        if not path.startswith('/') or path.startswith('//') or '\\' in path:
            raise ValueError('Use an absolute API path on the configured server.')
        token = self.token_file.read_text(encoding='utf-8-sig').strip()
        if len(token) < 32: raise ValueError('Invalid protected submit credential.')
        request = urllib.request.Request(self.origin + path, data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=15) as response: return json.load(response)
