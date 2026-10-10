"""Read-only live IMAP access and Windows account-bound credential storage."""
import ctypes
from ctypes import wintypes
import email
from email.policy import default
import imaplib
import json
import os
from pathlib import Path
import ssl


def quoted(value):
    if any(c in value for c in '\r\n\0'):
        raise ValueError('Invalid IMAP text.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def credential_path():
    return Path(os.environ['LOCALAPPDATA']) / 'PersonalAssistant/secrets/mail/imap.dpapi'


def crypt(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('This credential store requires Windows.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    dll = ctypes.WinDLL('crypt32', use_last_error=True)
    function = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def save_credentials(config, path=None):
    path = Path(path or credential_path()).resolve()
    repo = Path(__file__).resolve().parents[3]
    if path.is_relative_to(repo) or 'onedrive' in str(path).casefold():
        raise ValueError('Credentials must be outside the repository and OneDrive.')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.new')
    temporary.write_bytes(crypt(json.dumps(config).encode('utf-8')))
    temporary.replace(path)


class LiveIMAP:
    def __init__(self, config=None):
        self.config = config or json.loads(crypt(credential_path().read_bytes(), True))

    def __enter__(self):
        self.client = imaplib.IMAP4_SSL(self.config['host'], self.config.get('port', 993),
                                       ssl_context=ssl.create_default_context(), timeout=25)
        try:
            self.client.login(self.config['username'], self.config['password'])
        except Exception:
            self.client.logout()
            raise
        return self

    def __exit__(self, *args):
        try:
            self.client.logout()
        except (OSError, imaplib.IMAP4.error):
            pass

    def select(self, folder):
        status, _ = self.client.select(quoted(folder), readonly=True)
        if status != 'OK':
            raise RuntimeError('Mailbox could not be opened read-only.')
        return self.client.response('UIDVALIDITY')[1][0].decode()

    def search(self, folder='INBOX', subject=None, sender=None, limit=20):
        validity = self.select(folder)
        criteria = []
        for key, value in [('SUBJECT', subject), ('FROM', sender)]:
            if value:
                if any(c in value for c in '\r\n\0'):
                    raise ValueError('Invalid search text.')
                criteria.extend([key, quoted(value)])
        status, data = self.client.uid('SEARCH', None, *(criteria or ['ALL']))
        if status != 'OK':
            raise RuntimeError('IMAP search failed.')
        ids = data[0].split()
        return {'folder': folder, 'uidvalidity': validity, 'matches': len(ids),
                'messages': [self.fetch(uid, headers=True) for uid in reversed(ids[-limit:])]}

    def fetch(self, uid, headers=False):
        uid = uid.decode() if isinstance(uid, bytes) else str(uid)
        if not uid.isdigit():
            raise ValueError('UID must be numeric.')
        spec = '(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID REFERENCES IN-REPLY-TO)])' if headers else '(BODY.PEEK[])'
        status, data = self.client.uid('FETCH', uid, spec)
        if status != 'OK':
            raise RuntimeError('IMAP read failed.')
        raw = b''.join(item[1] for item in data if isinstance(item, tuple))
        if not raw:
            raise RuntimeError('Message no longer exists.')
        message = email.message_from_bytes(raw, policy=default)
        result = {'uid': uid, **{key.lower(): str(message.get(key, '')) for key in
                  ['From', 'To', 'Subject', 'Date', 'Message-ID', 'References', 'In-Reply-To']}}
        if not headers:
            body = message.get_body(preferencelist=('plain', 'html'))
            result['body'] = body.get_content() if body else ''
            result['attachments'] = [{'filename': part.get_filename(), 'mime': part.get_content_type()}
                                     for part in message.iter_attachments()]
        return result
