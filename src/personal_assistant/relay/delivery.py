"""Phone delivery mode: legacy Home Assistant, a dual-delivery migration window, or native Companion only."""
import logging

MODES = ('homeassistant', 'dual', 'native')


def resolve_mode(notifications):
    """delivery_mode wins. The legacy provider setting only ever meant native; other values stay Home Assistant."""
    mode = notifications.get('delivery_mode')
    if mode is None:
        return 'native' if notifications.get('provider') == 'companion' else 'homeassistant'
    if mode not in MODES:
        raise ValueError('delivery_mode must be one of: ' + ', '.join(MODES) + '.')
    return mode


class DualSender:
    """Journal for the native Companion, then send through Home Assistant while the native channel is proven."""
    fingerprint_namespace = 'dual-v1'

    def __init__(self, native, legacy):
        self.native, self.legacy = native, legacy

    def __call__(self, payload, revision=None):
        try:
            if revision is None:
                self.native(payload)
            else:
                self.native.renotify(payload, revision)
        except Exception as error:
            # A missing pairing or journal fault must not hold back the card that is known to work.
            logging.warning('Native journal failed (%s); Home Assistant delivery continues.', type(error).__name__)
        self.legacy(payload)

    def renotify(self, payload, revision):
        self(payload, revision)


def fcm_provider(notifications):
    """Firebase sender from companion_push, or the injected test provider."""
    from .mobile_push import FcmPush
    config = (notifications or {}).get('companion_push')
    return (notifications or {}).get('native_provider') or (FcmPush(config) if config else None)


def build_sender(notifications, store, provider):
    """Validate the notifications file against pairing and Firebase credentials; return (mode, sender)."""
    mode = resolve_mode(notifications)
    if mode != 'homeassistant':
        if not store:
            raise ValueError('Native notifications require Companion pairing.')
        if not provider:
            raise ValueError('Native notifications require companion_push credentials.')
    from .mobile_push import CompanionSender
    from .notifications import HomeAssistantPush
    if mode == 'native':
        sender = CompanionSender(store)
    else:
        legacy = notifications.get('sender') or HomeAssistantPush(notifications)
        sender = legacy if mode == 'homeassistant' else DualSender(CompanionSender(store), legacy)
    logging.warning('Phone notification delivery mode: %s%s.', mode,
                    ' (from legacy provider setting)' if mode == 'native' and notifications.get('delivery_mode') is None else '')
    return mode, sender


def delivery_status(mode, provider, store):
    """Owner view of delivery health. Identifiers are opaque; no content or token is ever included."""
    return {'mode': mode or 'disabled', 'fcm_configured': provider is not None,
            **(store.overview() if store else {'phones': []})}
