"""Linking, syncing and publishing for the money feature. Read-only towards the banks."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import time

from .enablebanking import EnableBanking
from .ledger import KINDS, Ledger, decision_version, public, summarise

BANKS = {'deutsche-bank': ('Deutsche Bank', 'DE'), 'revolut': ('Revolut', 'DE')}
UNATTENDED_PER_DAY = 4  # PSD2 limit on fetches without the owner present
HISTORY_DAYS = 90
RELAY = '/relay/v1/banking'
SUMMARY_LIMIT = 1900 * 1024  # leave room below installed Companion's 2 MiB response cap
TRANSACTION_PAGE_SIZE = 200


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
            from .statement_import import coalesce_provider_rows
            raws = coalesce_provider_rows(ledger, account['uid'], raws)
            new = ledger.store(account['uid'], raws, since)
            ledger.record_sync(account['uid'], True, len(raws))
            report.append({'bank': account['bank'], 'fetched': len(raws), 'new': new})
        except Exception as error:
            ledger.record_sync(account['uid'], False, error=str(error)[:300])
            report.append({'bank': account['bank'], 'error': str(error)[:300]})
    return report


COUNTING = ('expense', 'cash_withdrawal', 'fee', 'reimbursement', 'refund')


def answer(ledger, row, choice, note='', event_key=None):
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
                         'Set by you' + (': ' + note if note else ''), 1.0, None, 'owner',
                         event_key=event_key)


def settle(relay, ledger):
    """Applies the owner's answers given on the phone."""
    answers = relay.call(RELAY + '/answers')['items']
    rows = {r['id']: r for r in ledger.transactions(include_gone=True)}
    applied = 0
    for item in sorted(answers, key=lambda a: a['sequence']):
        if item['choice'] in ('correct', 'clarify'):
            row = rows.get(item['transaction'])
            key = 'relay:' + str(item.get('id') or item['sequence'])
            with ledger.db() as db:
                previous = db.execute("SELECT payload FROM audit_jobs WHERE kind='owner_answer' AND job_key=?", (key,)).fetchone()
            if previous:
                saved = json.loads(previous['payload'])
                if any(saved.get(k) != v for k, v in {'id': item['transaction'], 'choice': item['choice'], 'note': item.get('note', '')}.items()):
                    raise ValueError('Owner review ID already has different evidence')
            else:
                ledger.enqueue('owner_answer', key,
                           {'id': item['transaction'], 'choice': item['choice'], 'note': item.get('note', ''),
                            'authority': 'review_interpretation',
                            'decision_at': row.get('decided') if row else None,
                            'decision_version': decision_version(row) if row else None,
                            'question': row.get('question') if row else None,
                            'reasoning': row.get('reasoning') if row else None,
                            'evidence': {key: row.get(key) for key in ('day', 'amount_cents', 'counterparty', 'description', 'kind', 'category')} if row else None})
            applied += 1
        elif item['transaction'] in rows and answer(ledger, rows[item['transaction']], item['choice'], item.get('note', ''),
                                                    event_key='relay:' + str(item.get('id') or item['sequence'])):
            applied += 1
        else:
            ledger.enqueue('owner_answer', 'relay:' + str(item.get('id') or item['sequence']),
                           {'id': item['transaction'], 'choice': item['choice'], 'note': item.get('note', ''),
                            'status': 'unapplied'})
        # Acknowledge only after the local SQLite transaction has committed.
        relay.call(RELAY + '/answers/ack', {'through': item['sequence']})
    return applied


def ask_question(ledger, request_id, text, transaction=None):
    return ledger.enqueue('question', request_id, {'text': text, 'transaction': transaction})


def explain(ledger, request_id, transaction, text=''):
    return ledger.enqueue('explanation', request_id, {'transaction': transaction, 'text': text})


def record_offset(ledger, identity, day, kind, amount_cents, category, linked, reason, source):
    return ledger.add_adjustment(identity, day, kind, amount_cents, category, linked, reason, source)


def queue_enrichment(ledger, request_id='display-v1', identities=None, limit=12):
    """Queue a stable, explicitly bounded display-only batch; no bank fetch or model call."""
    if not isinstance(limit, int) or not 1 <= limit <= 12:
        raise ValueError('Enrichment limit must be between 1 and 12')
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 100:
        raise ValueError('Enrichment needs a short stable request ID')
    rows = ledger.transactions()
    known = {r['id']: r for r in rows}
    explicit = list(dict.fromkeys(identities)) if identities is not None else None
    if explicit is not None and (not explicit or len(explicit) > limit or any(i not in known for i in explicit)):
        raise ValueError('Choose between 1 and limit existing transactions')
    with ledger.db() as db:
        key = 'enrichment_request:' + request_id
        saved = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        selected = json.loads(saved['value']) if saved else explicit if explicit is not None else [
            r['id'] for r in rows if not r.get('annotation_by')][:limit]
        if explicit is not None and selected != explicit:
            raise ValueError('Enrichment request ID already selects different transactions')
        if len(selected) > limit:
            raise ValueError('Saved enrichment batch exceeds the requested limit')
        if not saved:
            db.execute('INSERT INTO settings VALUES(?,?)', (key, json.dumps(selected)))
        sequences = []
        for identity in selected:
            job_key = request_id + ':' + identity
            ledger._enqueue(db, 'enrichment', job_key, {'id': identity, 'authority': 'display_only'}, ledger.clock())
            sequences.append(db.execute("SELECT seq FROM audit_jobs WHERE kind='enrichment' AND job_key=?", (job_key,)).fetchone()[0])
        return {'request_id': request_id, 'ids': selected, 'sequences': sequences}


HISTORY_MONTHS = 120


def history(ledger, current_start, months=HISTORY_MONTHS):
    """Compact boards for earlier periods, newest first, so the phone can swipe back through them."""
    dates = [r['day'] for r in ledger.transactions() + ledger.adjustments() if r.get('day')]
    if not dates:
        return []
    earliest = min(dates)
    out, day = [], current_start
    for _ in range(months):
        day -= timedelta(days=1)
        past = summarise(ledger, day, insights=[])
        if past['period']['end'] <= earliest:
            break
        def compact(row):
            # Historical cards need the complete payment list, not repeated null
            # metadata and long remittance/account strings on every row. The
            # original statement evidence stays intact in the laptop ledger.
            fields=('id','day','amount_cents','counterparty','description','kind','reasoning',
                    'display_title','merchant_name','merchant_brand_id','annotation_note','tags',
                    'annotation_confidence','annotation_by')
            limits={'description':200,'reasoning':160,'annotation_note':160}
            return {k: (row[k][:limits[k]] if k in limits and isinstance(row[k],str) else row[k])
                    for k in fields if row.get(k) is not None and row.get(k)!='' and row.get(k)!=[]}
        out.append({'period': past['period'], 'spent_cents': past['spent_cents'], 'categories': past['categories'],
                    'fixed_costs': past['fixed_costs'],
                    'category_transactions': {k: [compact(r) for r in v] for k, v in past['category_transactions'].items()}})
        day = date.fromisoformat(past['period']['start'])
    return out


def publish(relay, ledger, today=None, transaction_cursor=None, page_size=TRANSACTION_PAGE_SIZE):
    """Publish a bounded summary with complete category details and a stable transaction cursor.

    Category and fixed-cost detail lists are never sliced. The generic transaction feed is
    paged by (day,id); an oversized category payload fails before relay storage, never silently
    publishes an incomplete category page.
    """
    if not 1 <= page_size <= TRANSACTION_PAGE_SIZE:
        raise ValueError('page_size must be between 1 and %d' % TRANSACTION_PAGE_SIZE)
    summary = summarise(ledger, today)
    start, end = summary['period']['start'], summary['period']['end']
    rows = ledger.transactions(start, end)
    rows.sort(key=lambda row: (row['day'] or '', row['id']), reverse=True)
    if transaction_cursor is not None:
        if not isinstance(transaction_cursor, dict) or not isinstance(transaction_cursor.get('day'), str) or not isinstance(transaction_cursor.get('id'), str):
            raise ValueError('transaction_cursor must contain day and id')
        cursor_key = (transaction_cursor['day'], transaction_cursor['id'])
        rows = [row for row in rows if (row['day'] or '', row['id']) < cursor_key]
    selected = rows[:page_size]
    next_cursor = ({'day': selected[-1]['day'], 'id': selected[-1]['id']}
                   if len(rows) > len(selected) and selected else None)
    summary['transactions'] = [public(row) for row in selected]
    summary['transactions_page'] = {'limit': page_size, 'returned': len(selected),
                                    'has_more': next_cursor is not None, 'next_cursor': next_cursor}
    summary['months'] = history(ledger, date.fromisoformat(start))
    from .tools import logo_catalog
    summary['merchant_logos'] = logo_catalog(ledger)
    summary['generated'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    encoded_size = len(json.dumps(summary, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
    if encoded_size > SUMMARY_LIMIT:
        raise ValueError('Complete Money summary exceeds the %d-byte relay limit; category details were not published.' % SUMMARY_LIMIT)
    relay.call(RELAY + '/summary', summary, method='PUT')
    return summary
