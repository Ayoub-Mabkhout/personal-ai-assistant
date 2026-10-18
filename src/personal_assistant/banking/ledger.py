"""Private transaction ledger. Code here only stores, deduplicates by bank identifiers and adds up.

Every judgement about what a transaction is (internal transfer, reimbursement, refund, duplicate,
category, whether it counts against the allowance) is a decision recorded with its reasoning,
made by the AI agent or by the owner. Totals are sums over those decisions.
"""
from calendar import monthrange
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import time

KINDS = ('expense', 'fixed_cost', 'cash_withdrawal', 'fee', 'income', 'salary', 'internal_transfer', 'reimbursement',
         'refund', 'duplicate', 'lent', 'repaid_to_me', 'savings', 'other')
DEFAULTS = {'allowance': {'amount_cents': 120000, 'currency': 'EUR', 'period': 'month', 'start_day': 1,
                          'definition': 'Day-to-day spending. Rent and other fixed costs do not count against it, '
                                        'but they do count in net savings.'}}


def cents(value):
    return int((Decimal(str(value)) * 100).to_integral_value())


def normalise(account, raw):
    """Maps a provider transaction to a ledger row with a stable identity."""
    amount = raw.get('transaction_amount') or {}
    debit = raw.get('credit_debit_indicator') == 'DBIT'
    value = cents(amount.get('amount', '0'))
    value = -abs(value) if debit else abs(value)
    party = (raw.get('creditor') if debit else raw.get('debtor')) or {}
    party_account = (raw.get('creditor_account') if debit else raw.get('debtor_account')) or {}
    status = 'pending' if raw.get('status') == 'PDNG' else 'booked'
    reference = raw.get('entry_reference') or raw.get('transaction_id')
    day = raw.get('booking_date') or raw.get('value_date') or raw.get('transaction_date')
    description = ' '.join(raw.get('remittance_information') or []).strip()
    if reference:
        identity = '%s:%s' % (account, reference)
    else:
        # Without a bank reference (often pending card payments) the content is the identity.
        basis = json.dumps([account, status, day, value, party.get('name'), description], ensure_ascii=False)
        identity = '%s:h%s' % (account, hashlib.sha256(basis.encode()).hexdigest()[:24])
    return {'id': identity, 'account': account, 'status': status, 'day': day, 'amount_cents': value,
            'currency': amount.get('currency', 'EUR'), 'counterparty': party.get('name') or '',
            'counterparty_iban': party_account.get('iban') or '', 'description': description,
            'raw': json.dumps(raw, ensure_ascii=False, sort_keys=True)}


class Ledger:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        with db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS banks(bank TEXT PRIMARY KEY,country TEXT NOT NULL,session_id TEXT NOT NULL,valid_until TEXT,linked REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS accounts(uid TEXT PRIMARY KEY,bank TEXT NOT NULL,iban TEXT,name TEXT,currency TEXT);
            CREATE TABLE IF NOT EXISTS transactions(id TEXT PRIMARY KEY,account TEXT NOT NULL,status TEXT NOT NULL,day TEXT,
                amount_cents INTEGER NOT NULL,currency TEXT NOT NULL,counterparty TEXT,counterparty_iban TEXT,description TEXT,
                raw TEXT NOT NULL,first_seen REAL NOT NULL,updated REAL NOT NULL,gone REAL);
            CREATE INDEX IF NOT EXISTS transactions_day ON transactions(day);
            CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,kind TEXT NOT NULL,category TEXT,counts INTEGER NOT NULL,
                linked TEXT NOT NULL DEFAULT '[]',reasoning TEXT,confidence REAL,question TEXT,by TEXT NOT NULL,at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS syncs(at REAL NOT NULL,account TEXT NOT NULL,ok INTEGER NOT NULL,count INTEGER,error TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
        db.close()

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        finally:
            db.close()

    def setting(self, key):
        with self.db() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else DEFAULTS.get(key)

    def set_setting(self, key, value):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value)))

    def link(self, bank, country, session):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO banks VALUES(?,?,?,?,?)',
                       (bank, country, session['session_id'], (session.get('access') or {}).get('valid_until'), self.clock()))
            for account in session.get('accounts') or []:
                db.execute('INSERT OR REPLACE INTO accounts VALUES(?,?,?,?,?)', (account['uid'], bank,
                    (account.get('account_id') or {}).get('iban'), account.get('name') or account.get('product'), account.get('currency')))

    def banks(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM banks ORDER BY bank')]

    def accounts(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM accounts ORDER BY bank')]

    def syncs_since(self, account, since):
        with self.db() as db:
            return db.execute('SELECT COUNT(*) FROM syncs WHERE account=? AND at>=?', (account, since)).fetchone()[0]

    def record_sync(self, account, ok, count=None, error=None):
        with self.db() as db:
            db.execute('INSERT INTO syncs VALUES(?,?,?,?,?)', (self.clock(), account, int(ok), count, error))

    def store(self, account, raws, date_from):
        """Upserts one account's fetch. Pending rows of the fetched window that the bank no longer
        lists (they booked under a new reference, or were dropped) are marked gone, not deleted."""
        now, rows = self.clock(), {}
        for raw in raws:
            row = normalise(account, raw)
            rows[row['id']] = row
        new = 0
        with self.db() as db:
            for row in rows.values():
                known = db.execute('SELECT 1 FROM transactions WHERE id=?', (row['id'],)).fetchone()
                if known:
                    db.execute('UPDATE transactions SET status=?,day=?,amount_cents=?,counterparty=?,counterparty_iban=?,description=?,raw=?,'
                               'updated=?,gone=NULL WHERE id=?', (row['status'], row['day'], row['amount_cents'], row['counterparty'],
                               row['counterparty_iban'], row['description'], row['raw'], now, row['id']))
                else:
                    new += 1
                    db.execute('INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)', (row['id'], account, row['status'], row['day'],
                               row['amount_cents'], row['currency'], row['counterparty'], row['counterparty_iban'], row['description'],
                               row['raw'], now, now))
            listed = list(rows) or ['']
            db.execute('UPDATE transactions SET gone=? WHERE account=? AND status=\'pending\' AND gone IS NULL AND day>=? AND id NOT IN (%s)'
                       % ','.join('?' * len(listed)), [now, account, date_from] + listed)
        return new

    def transactions(self, since=None, until=None, undecided=False, include_gone=False):
        query = ('SELECT t.*,a.bank,d.kind,d.category,d.counts,d.linked,d.reasoning,d.confidence,d.question,d.by,d.at decided '
                 'FROM transactions t JOIN accounts a ON a.uid=t.account LEFT JOIN decisions d ON d.id=t.id WHERE 1=1')
        args = []
        if since: query += ' AND t.day>=?'; args.append(since)
        if until: query += ' AND t.day<?'; args.append(until)
        if undecided: query += ' AND d.id IS NULL'
        if not include_gone: query += ' AND t.gone IS NULL'
        with self.db() as db:
            return [dict(r) for r in db.execute(query + ' ORDER BY t.day DESC,t.first_seen DESC', args)]

    def decide(self, identity, kind, category, counts, linked, reasoning, confidence, question, by):
        if kind not in KINDS:
            raise ValueError('Unknown kind %r' % kind)
        with self.db() as db:
            if not db.execute('SELECT 1 FROM transactions WHERE id=?', (identity,)).fetchone():
                raise KeyError(identity)
            current = db.execute('SELECT by FROM decisions WHERE id=?', (identity,)).fetchone()
            if current and current['by'] == 'owner' and by != 'owner':
                return False  # the owner's word stands
            db.execute('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?)', (identity, kind, category, int(bool(counts)),
                       json.dumps(list(linked or [])), reasoning, confidence, question or None, by, self.clock()))
        return True

    def corrections(self, limit=60):
        query = ('SELECT t.day,t.amount_cents,t.counterparty,t.description,a.bank,d.kind,d.category,d.counts,d.reasoning FROM decisions d '
                 'JOIN transactions t ON t.id=d.id JOIN accounts a ON a.uid=t.account WHERE d.by=\'owner\' ORDER BY d.at DESC LIMIT ?')
        with self.db() as db:
            return [dict(r) for r in db.execute(query, (limit,))]


def period(today, allowance):
    start_day = allowance.get('start_day', 1)
    start = today.replace(day=min(start_day, monthrange(today.year, today.month)[1]))
    if start > today:
        previous = (today.replace(day=1) - timedelta(days=1))
        start = previous.replace(day=min(start_day, monthrange(previous.year, previous.month)[1]))
    following = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
    end = following.replace(day=min(start_day, monthrange(following.year, following.month)[1]))
    return start, end


def summarise(ledger, today=None, insights=None):
    """Arithmetic over decided transactions for the current allowance period."""
    today = today or date.today()
    allowance = ledger.setting('allowance')
    start, end = period(today, allowance)
    rows = ledger.transactions(start.isoformat(), end.isoformat())
    counted = [r for r in rows if r['kind'] and r['counts']]
    real = [r for r in rows if r['kind'] not in ('internal_transfer', 'duplicate')]
    spent = -sum(r['amount_cents'] for r in counted)
    remaining = allowance['amount_cents'] - spent
    days_total, days_left = (end - start).days, (end - today).days
    elapsed = days_total - days_left + 1
    categories = {}
    for r in counted:
        categories[r['category'] or 'Other'] = categories.get(r['category'] or 'Other', 0) - r['amount_cents']
    review = [r for r in rows if r['kind'] and r['question'] and r['by'] == 'ai']
    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat(), 'days_left': days_left, 'days_total': days_total},
        'allowance': allowance, 'spent_cents': spent, 'remaining_cents': remaining,
        'safe_per_day_cents': max(0, remaining) // max(1, days_left),
        'expected_cents': allowance['amount_cents'] * elapsed // days_total,
        'income_cents': sum(r['amount_cents'] for r in real if r['amount_cents'] > 0),
        'outgoing_cents': -sum(r['amount_cents'] for r in real if r['amount_cents'] < 0),
        'net_cents': sum(r['amount_cents'] for r in real),
        'undecided': sum(1 for r in rows if not r['kind']),
        'decided': sum(1 for r in rows if r['kind']),
        'categories': sorted(({'name': k, 'cents': v} for k, v in categories.items()), key=lambda c: -c['cents']),
        'review': [public(r) for r in review],
        'transactions': [public(r) for r in rows[:200]],
        'insights': insights if insights is not None else ledger.setting('insights') or [],
        'banks': [{'bank': b['bank'], 'valid_until': b['valid_until']} for b in ledger.banks()],
    }


def public(row):
    return {k: row[k] for k in ('id', 'bank', 'status', 'day', 'amount_cents', 'currency', 'counterparty', 'description', 'kind',
                                'category', 'counts', 'reasoning', 'confidence', 'question', 'by')} | {'linked': json.loads(row['linked'] or '[]')}
