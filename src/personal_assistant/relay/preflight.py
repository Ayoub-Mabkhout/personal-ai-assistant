"""Deploy gate: prove the notifications file can start the relay and that Firebase accepts the service account.

A bad file otherwise crash-loops the relay and takes tasks, groceries and voice down with notifications.
Run inside the relay image before the container is replaced; it never sends a push or prints a secret.
"""
import json
import os
from pathlib import Path
import sys

# Rejections that mean the credential, project or permission is wrong, as opposed to a transient or unexpected reply.
BLOCKING = {'UNAUTHENTICATED', 'PERMISSION_DENIED', 'NOT_FOUND', 'THIRD_PARTY_AUTH_ERROR'}
# Transient token-endpoint failures do not invalidate the configured service account.
TRANSIENT = {'OAUTH_UNREACHABLE', 'OAUTH_UNAVAILABLE', 'OAUTH_QUOTA_EXCEEDED'}


def describe(error):
    """Our own validation messages and file names are safe to print; anything else is reduced to its class."""
    if isinstance(error, KeyError):
        return 'missing setting ' + str(error)
    if isinstance(error, ValueError):
        return str(error)
    return type(error).__name__ + (' ' + str(error.filename) if getattr(error, 'filename', None) else '')


def check(notifications, paired, out=print):
    """Validate a parsed notifications file; returns True when the relay would start and the credential works."""
    from .delivery import build_sender, fcm_provider
    from .mobile_push import FcmPush, reason
    from .notifications import NotificationPump
    try:
        provider = fcm_provider(notifications) if paired else None
        # Only pairing matters here; the real store is the groceries phones database.
        mode, sender = build_sender(notifications, object() if paired else None, provider)
        NotificationPump({}, sender, notifications['public_url'], visibility=notifications.get('visibility', 'private'))
    except Exception as error:
        out('FAIL config: ' + describe(error))
        return False
    out('ok   config: delivery mode ' + mode)
    if not isinstance(provider, FcmPush):
        out('ok   firebase: no companion_push configured' if not provider else 'ok   firebase: injected provider')
        return True
    try:
        provider.bearer()
    except Exception as error:
        code = reason(error)
        out(('warn firebase oauth token exchange inconclusive: ' if code in TRANSIENT else 'FAIL firebase oauth token exchange: ') + code)
        return code in TRANSIENT
    out('ok   firebase oauth token exchange')
    try:
        provider.dry_run()
    except Exception as error:
        code = reason(error)
        out(('FAIL firebase send dry run: ' if code in BLOCKING else 'warn firebase send dry run inconclusive: ') + code)
        return code not in BLOCKING
    out('ok   firebase send dry run')
    return True


def main(environ=os.environ, out=print):
    path = Path(environ.get('ASSISTANT_NOTIFICATIONS_CONFIG', '/data/notifications.json'))
    try:
        notifications = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
    except (OSError, ValueError) as error:
        out('FAIL config: notifications file unreadable (' + type(error).__name__ + ')')
        return 1
    if not isinstance(notifications, dict) and notifications is not None:
        out('FAIL config: notifications file must hold a JSON object')
        return 1
    if not notifications or not notifications.get('enabled', False):
        out('ok   notifications are disabled; nothing to check')
        return 0
    return 0 if check(notifications, bool(environ.get('ASSISTANT_GROCERIES_TOKEN_FILE')), out) else 1


if __name__ == '__main__':
    sys.exit(main())
