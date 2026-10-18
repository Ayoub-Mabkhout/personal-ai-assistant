"""Linking, syncing and publishing for the money feature. Read-only towards the banks."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import time

from .enablebanking import EnableBanking
from .ledger import KINDS, Ledger, summarise

BANKS = {'deutsche-bank': ('Deutsche Bank', 'DE'), 'revolut': ('Revolut', 'DE')}
UNATTENDED_PER_DAY = 4  # PSD2 limit on fetches without the owner present
HISTORY_DAYS = 90
RELAY = '/relay/v1/banking'


def home():
    return Path.home() / '.personal-assistant'


def open_ledger(config):
    return Ledger(Path(config.get('banking_ledger') or home() / 'banking' / 'ledger.sqlite3'))


def provider(config):
    return EnableBanking(Path(config.get('banking_application') or home() / 'secrets' / 'banking' / 'application.json'))


def link(config, key, relay, ledger, client=None, show=print, wait=900, poll=3):
    """Starts a new consent, waits for the bank's redirect through the relay and stores the session."""
    name, country = BANKS[key]
    client = client or provider(config)
    state = secrets.token_urlsafe(24)
    relay.call(RELAY + '/pending', {'state': state})
    started = client.start(name, country, state)
    show(started['url'])
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        result = relay.call(RELAY + '/pending/' + state)
        if result['status'] == 'returned':
            session = client.session(result['code'])
            ledger.link(name, country, session)
            return session
        if result['status'] == 'error':
            raise RuntimeError('The bank link was not completed (%s).' % result.get('error'))
        time.sleep(poll)
    raise TimeoutError('No answer from the bank within %d minutes.' % (wait // 60))


def sync(config, ledger, client=None, today=None, attended=False):
    """Fetches each linked account at most UNATTENDED_PER_DAY times a day unless the owner is present."""
    client, today = client or provider(config), today or date.today()
    report = []
    day_start = datetime.combine(today, datetime.min.time()).timestamp()
    for account in ledger.accounts():
        if not attended and ledger.syncs_since(account['uid'], day_start) >= UNATTENDED_PER_DAY:
            report.append({'bank': account['bank'], 'skipped': 'daily limit'})
            continue
        known = ledger.transactions()
        since = (today - timedelta(days=HISTORY_DAYS if not any(r['account'] == account['uid'] for r in known) else 14)).isoformat()
        try:
            raws = client.transactions(account['uid'], since)
            new = ledger.store(account['uid'], raws, since)
            ledger.record_sync(account['uid'], True, len(raws))
            report.append({'bank': account['bank'], 'fetched': len(raws), 'new': new})
        except Exception as error:
            ledger.record_sync(account['uid'], False, error=str(error)[:300])
            report.append({'bank': account['bank'], 'error': str(error)[:300]})
    return report


COUNTING = ('expense', 'cash_withdrawal', 'fee', 'reimbursement', 'refund')


def answer(ledger, row, choice, note=''):
    """The owner's word on one transaction: 'confirm' keeps the agent's decision, a kind replaces it."""
    if choice == 'confirm':
        if not row['kind']:
            return False
        kind, counts = row['kind'], row['counts']
    elif choice in KINDS:
        kind = choice
        counts = row['counts'] if kind == row['kind'] else kind in COUNTING
    else:
        return False
    return ledger.decide(row['id'], kind, row['category'], counts, json.loads(row['linked'] or '[]'),
                         'Set by you' + (': ' + note if note else ''), 1.0, None, 'owner')


def settle(relay, ledger):
    """Applies the owner's answers given on the phone."""
    answers = relay.call(RELAY + '/answers')['items']
    rows = {r['id']: r for r in ledger.transactions(include_gone=True)}
    applied = sum(1 for a in answers if a['transaction'] in rows and answer(ledger, rows[a['transaction']], a['choice'], a.get('note', '')))
    if answers:
        relay.call(RELAY + '/answers/ack', {'through': max(a['sequence'] for a in answers)})
    return applied


def publish(relay, ledger, today=None):
    summary = summarise(ledger, today)
    summary['transactions'] = summary['transactions'][:60]
    summary['generated'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    relay.call(RELAY + '/summary', summary, method='PUT')
    return summary
