"""Encrypted Web Push to browser vendors' HTTPS endpoints."""

import base64
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ..relay.client import NoRedirect


def decode(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid push key')
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def endpoint_origin(endpoint):
    url = urlsplit(endpoint)
    host = url.hostname or ''
    allowed = (host in ('fcm.googleapis.com', 'updates.push.services.mozilla.com')
               or re.fullmatch(r'[a-z0-9-]+\.push\.apple\.com', host)
               or re.fullmatch(r'[a-z0-9-]+\.notify\.windows\.com', host))
    if not allowed or url.scheme != 'https' or url.netloc != host or not url.path.startswith('/') or url.fragment:
        raise ValueError('Unsupported browser push endpoint')
    return 'https://' + host


class WebPush:
    def __init__(self, private_key_file, subject):
        from py_vapid import Vapid02
        self.vapid = Vapid02.from_pem(Path(private_key_file).read_bytes())
        if not isinstance(self.vapid.private_key.curve, ec.SECP256R1):
            raise ValueError('Use a P-256 Web Push private key')
        self.subject = subject
        self.opener = build_opener(NoRedirect)
        point = self.vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.public_key = base64.urlsafe_b64encode(point).rstrip(b'=').decode()

    def send(self, subscription, payload, ttl):
        import http_ece
        endpoint = subscription['endpoint']
        origin = endpoint_origin(endpoint)
        keys = subscription['keys']
        encrypted = http_ece.encrypt(payload, private_key=ec.generate_private_key(ec.SECP256R1()),
                                     dh=decode(keys['p256dh']), auth_secret=decode(keys['auth']))
        headers = self.vapid.sign({'aud': origin, 'sub': self.subject, 'exp': int(time.time()) + 3600})
        headers.update({'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream',
                        'TTL': str(ttl), 'Urgency': 'high', 'Topic': payload_topic(payload)})
        try:
            with self.opener.open(Request(endpoint, encrypted, headers, method='POST'), timeout=8) as response:
                return response.status
        except HTTPError as error:
            error.close()
            return error.code


def payload_topic(payload):
    from hashlib import sha256
    return base64.urlsafe_b64encode(sha256(payload).digest()[:24]).decode()
