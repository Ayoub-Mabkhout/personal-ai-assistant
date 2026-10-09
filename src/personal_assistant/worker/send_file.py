"""Send one owner-requested laptop file to the paired Companion phone through the relay.

The relay stores it briefly and the phone saves it to Downloads, then confirms. A stable ID
makes retries safe: an ID the relay already holds is reported, never uploaded twice.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import urllib.error
import urllib.request

from .runtime import RelayClient, TransportError

ID = re.compile(r'[A-Za-z0-9_-]{8,64}')


def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def default_id(name, sha256, note):
    """Same file, name and note give the same ID, so a repeated tool call cannot duplicate it."""
    return 'file-' + hashlib.sha256('\0'.join((name, sha256, note)).encode()).hexdigest()[:40]


class FileClient:
    """Relay transport: JSON calls plus one streamed PUT, using the protected token file."""
    def __init__(self, relay):
        self.relay = relay

    def call(self, path, payload=None):
        return self.relay.call(path, payload)

    def upload(self, path, source, size, headers):
        token = self.relay.token_file.read_text().strip()
        request = urllib.request.Request(self.relay.base + path, data=source, method='PUT', headers={
            **headers, 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/octet-stream',
            'Content-Length': str(size)})
        try:
            with self.relay.opener.open(request, timeout=max(60, size // (256 * 1024))) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = ''
            try:
                detail = json.load(error).get('detail', '')
            except Exception:
                pass
            if detail:
                raise UploadRejected(error.code, detail) from None
            raise TransportError(error.code) from None
        except (OSError, TimeoutError, ValueError):
            raise TransportError() from None


class UploadRejected(TransportError):
    def __init__(self, status, detail):
        super().__init__(status)
        self.detail = detail
        self.args = ('Relay HTTP %s: %s' % (status, detail),)


def client_from_config(config):
    token = config.get('worker_token_file') or config.get('submit_token_file')
    if not token:
        raise ValueError('The worker config needs worker_token_file or submit_token_file.')
    return FileClient(RelayClient(config['relay_url'], token, timeout=20))


def record(config, entry):
    """Local action history beside the agent runtime, so later runs can see what was already sent."""
    runtime = Path(config.get('agent_runtime_dir', Path.home() / '.personal-assistant/agents'))
    try:
        runtime.mkdir(parents=True, exist_ok=True)
        with open(runtime / 'file-drops.jsonl', 'a', encoding='utf-8') as log:
            log.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError:
        pass


def select_phone(phones, requested=None):
    active = [phone['id'] for phone in phones]
    if requested:
        if requested not in active:
            raise ValueError('That phone is not paired or has been revoked. Run with --list-phones.')
        return requested
    if len(active) == 1:
        return active[0]
    if not active:
        raise ValueError('Install and pair Assistant Companion first; no active phone is paired.')
    raise ValueError('More than one phone is paired. Ask which phone to use and pass its ID with --phone.')


def send(client, path, name=None, note='', mime=None, phone=None, request_id=None):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Not a file: ' + str(path))
    name = ' '.join((name or path.name).split())
    note = (note or '').strip()
    size = path.stat().st_size
    relay = client.call('/v1/files/phones')
    max_bytes = relay['max_bytes']
    if size > max_bytes:
        raise ValueError('File is %.1f MiB; the phone transfer limit is %d MiB.' % (size / 1048576, max_bytes // 1048576))
    sha256 = digest(path)
    mime = mime or mimetypes.guess_type(name)[0] or 'application/octet-stream'
    identifier = request_id or default_id(name, sha256, note)
    if not ID.fullmatch(identifier):
        raise ValueError('Use an ID of 8-64 letters, numbers, underscores or hyphens.')
    try:
        existing = client.call('/v1/files/' + identifier)
    except TransportError as error:
        if error.status != 404:
            raise
        existing = None
    if existing:
        if existing['sha256'] != sha256 or existing['name'] != name:
            raise ValueError('That ID already belongs to a different file; choose another ID.')
        # Ready: already waiting for the phone. Delivered, expired or cancelled: never resent under this ID.
        return {**existing, 'created_now': False}
    manifest = {'name': name, 'size': size, 'sha256': sha256, 'mime': mime, 'note': note}
    if phone:
        manifest['phone'] = select_phone(relay['phones'], phone)
    else:
        select_phone(relay['phones'])
    encoded = base64.b64encode(json.dumps(manifest, ensure_ascii=False).encode()).decode()
    with open(path, 'rb') as source:
        # The relay rejects the upload if the bytes no longer match this checksum.
        return client.upload('/v1/files/' + identifier, source, size, {'X-File-Manifest': encoded})


def send_from_config(config, path, **options):
    client = client_from_config(config)
    result = send(client, path, **options)
    record(config, {'at': datetime.now(timezone.utc).isoformat(), 'id': result['id'], 'source': str(Path(path).resolve()),
                    'name': result['name'], 'sha256': result['sha256'], 'size': result['size'], 'state': result['state'],
                    'created_now': result.get('created_now', False)})
    return result
