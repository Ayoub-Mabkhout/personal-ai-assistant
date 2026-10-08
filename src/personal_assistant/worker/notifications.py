"""HA persistent results and optional Android push; API acceptance is not delivery."""
import json
from pathlib import Path
import time
import urllib.parse
import urllib.error
import urllib.request
from .runtime import NoRedirect


class HomeAssistantNotifier:
    def __init__(self, config):
        self.base = config['homeassistant_url'].rstrip('/')
        parsed = urllib.parse.urlsplit(self.base)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.path:
            raise ValueError('Use the Home Assistant HTTPS origin.')
        self.auth_file = Path(config['homeassistant_auth_file'])
        self.mobile_service = config.get('mobile_notify_service')
        if self.mobile_service and not self.mobile_service.startswith('mobile_app_'):
            raise ValueError('Only the configured mobile app may receive results.')
        self.token, self.expires = None, 0
        self.opener = urllib.request.build_opener(NoRedirect)

    def call(self, path, payload=None, authenticated=True):
        if authenticated and time.time() >= self.expires:
            auth = json.loads(self.auth_file.read_text())
            response = self.call('/auth/token', {'grant_type': 'refresh_token',
                'refresh_token': auth['refresh_token'], 'client_id': auth['client_id']}, False)
            self.token, self.expires = response['access_token'], time.time() + response['expires_in'] - 60
        headers = {'Content-Type': 'application/json' if authenticated else 'application/x-www-form-urlencoded'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + self.token
        data = (json.dumps(payload).encode() if payload is not None else None) if authenticated else urllib.parse.urlencode(payload).encode()
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if authenticated and exc.code == 401:
                self.token, self.expires = None, 0
            raise

    def __call__(self, job_id, outcome):
        summary = outcome['result']['summary'][:2000]
        title = 'Assistant result' if outcome['state'] == 'completed' else 'Assistant needs attention'
        self.call('/api/services/persistent_notification/create',
            {'title': title, 'message': summary, 'notification_id': 'assistant-' + job_id})
        if self.mobile_service:
            self.call('/api/services/notify/' + self.mobile_service,
                {'title': title, 'message': summary, 'data': {'tag': 'assistant-' + job_id}})
