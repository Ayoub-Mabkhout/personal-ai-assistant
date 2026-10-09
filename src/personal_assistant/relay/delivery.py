"""Phone delivery mode: Native Companion notification delivery."""
import logging

MODES = ('native',)


def resolve_mode(notifications):
    mode=notifications.get('delivery_mode','native')
    if mode != 'native': raise ValueError('Home Assistant delivery is retired; set delivery_mode to native.')
    return mode


def fcm_provider(notifications):
    from .mobile_push import FcmPush
    config=(notifications or {}).get('companion_push')
    return (notifications or {}).get('native_provider') or (FcmPush(config) if config else None)


def build_sender(notifications,store,provider):
    mode=resolve_mode(notifications)
    if not store: raise ValueError('Native notifications require Companion pairing.')
    if not provider: raise ValueError('Native notifications require companion_push credentials.')
    from .mobile_push import CompanionSender
    sender = CompanionSender(store)
    logging.warning('Phone notification delivery mode: native.')
    return mode, sender


def delivery_status(mode, provider, store):
    """Owner view of delivery health. Identifiers are opaque; no content or token is ever included."""
    return {'mode': mode or 'disabled', 'fcm_configured': provider is not None,
            **(store.overview() if store else {'phones': []})}
