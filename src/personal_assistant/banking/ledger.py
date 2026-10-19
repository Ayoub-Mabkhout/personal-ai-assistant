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
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .merchants import BRAND_CATALOG, supported_brand

KINDS = ('expense', 'fixed_cost', 'cash_withdrawal', 'fee', 'income', 'salary', 'internal_transfer', 'reimbursement',
         'refund', 'duplicate', 'lent', 'repaid_to_me', 'savings', 'other')
RECURRING_COST_KINDS = ('expense', 'fixed_cost', 'fee')
CATEGORY_GROUPS = ('fixed', 'elective', 'income', 'savings', 'transfer')
DEFAULTS = {'allowance': {'mode': 'auto', 'currency': 'EUR', 'period': 'month', 'start_day': 1,
                          'definition': 'Regular monthly income less recurring costs; fixed costs do not count as elective spending.'}}
UNSET = object()


def decision_version(row):
    """Exact decision revision, including edits made at an identical clock time."""
    row = dict(row)
    fields = ('kind', 'category', 'counts', 'linked', 'reasoning', 'confidence', 'question', 'by',
              'recurring', 'monthly_cents', 'coverage_months', 'series_key')
    return hashlib.sha256(json.dumps({**{k: row.get(k) for k in fields},
                                     'at': row.get('decided', row.get('at'))}, sort_keys=True).encode()).hexdigest()


def _process_alive(pid):
    """A live orphaned model process keeps its lease fenced after the parent exits."""
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = (ctypes.c_uint, ctypes.c_int, ctypes.c_uint)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


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
            columns = {r[1] for r in db.execute('PRAGMA table_info(decisions)')}
            for name, definition in (('recurring', 'INTEGER NOT NULL DEFAULT 0'),
                                     ('monthly_cents', 'INTEGER'), ('coverage_months', "TEXT NOT NULL DEFAULT '[]'"),
                                     ('series_key', 'TEXT')):
                if name not in columns:
                    db.execute('ALTER TABLE decisions ADD COLUMN %s %s' % (name, definition))
            db.executescript('''
            CREATE TABLE IF NOT EXISTS adjustments(id TEXT PRIMARY KEY,day TEXT NOT NULL,kind TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,category TEXT NOT NULL,linked TEXT NOT NULL,reason TEXT NOT NULL,
                source TEXT NOT NULL,at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_jobs(seq INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,
                job_key TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
                token TEXT,attempts INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL,
                UNIQUE(kind,job_key));
            CREATE INDEX IF NOT EXISTS audit_jobs_state_seq ON audit_jobs(state,seq);
            CREATE TABLE IF NOT EXISTS audit_state(id INTEGER PRIMARY KEY CHECK(id=1),session_id TEXT,
                lease_token TEXT,lease_until REAL,updated REAL NOT NULL,process_pid INTEGER);
            INSERT OR IGNORE INTO audit_state(id,updated) VALUES(1,0);
            CREATE TABLE IF NOT EXISTS audit_outputs(job_seq INTEGER PRIMARY KEY,answer TEXT NOT NULL,at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS transaction_annotations(id TEXT PRIMARY KEY,display_title TEXT NOT NULL,
                merchant_name TEXT NOT NULL,merchant_brand_id TEXT,annotation_note TEXT NOT NULL,tags TEXT NOT NULL,
                confidence REAL NOT NULL,evidence TEXT NOT NULL,by TEXT NOT NULL,at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS merchant_logos(merchant_name TEXT PRIMARY KEY,domain TEXT NOT NULL,
                data_uri TEXT NOT NULL,evidence TEXT NOT NULL,source_url TEXT NOT NULL,at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS categories(name TEXT PRIMARY KEY,emoji TEXT,grp TEXT NOT NULL DEFAULT 'elective',
                description TEXT NOT NULL DEFAULT '',budget_cents INTEGER,suggested_budget_cents INTEGER,
                by TEXT NOT NULL DEFAULT 'ai',created REAL NOT NULL,updated REAL NOT NULL);
            ''')
            # Categories already used by decisions become catalogue entries the auditor can then curate.
            db.execute("""INSERT OR IGNORE INTO categories(name,grp,created,updated)
                SELECT category,CASE WHEN MAX(kind='fixed_cost') THEN 'fixed' WHEN MAX(kind IN ('income','salary')) THEN 'income'
                ELSE 'elective' END,0,0 FROM decisions WHERE category IS NOT NULL AND category<>'' GROUP BY category""")
            if 'process_pid' not in {r[1] for r in db.execute('PRAGMA table_info(audit_state)')}:
                db.execute('ALTER TABLE audit_state ADD COLUMN process_pid INTEGER')
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

    def settings_prefix(self, prefix):
        with self.db() as db:
            return [{'key': row['key'], 'value': json.loads(row['value'])}
                    for row in db.execute('SELECT key,value FROM settings ORDER BY key')
                    if row['key'].startswith(prefix)]

    def set_setting(self, key, value):
        if key == 'allowance' and isinstance(value, dict) and 'amount_cents' in value:
            value = {**value, 'mode': 'pinned'}
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
                    self._enqueue(db, 'transaction', row['id'], {'id': row['id']}, now)
            listed = list(rows) or ['']
            db.execute('UPDATE transactions SET gone=? WHERE account=? AND status=\'pending\' AND gone IS NULL AND day>=? AND id NOT IN (%s)'
                       % ','.join('?' * len(listed)), [now, account, date_from] + listed)
        return new

    def transactions(self, since=None, until=None, undecided=False, include_gone=False):
        query = ('SELECT t.*,a.bank,d.kind,d.category,d.counts,d.linked,d.reasoning,d.confidence,d.question,d.by,d.at decided '
                 ',d.recurring,d.monthly_cents,d.coverage_months,d.series_key '
                 ',n.display_title,n.merchant_name,n.merchant_brand_id,n.annotation_note,n.tags annotation_tags '
                 ',n.confidence annotation_confidence,n.evidence annotation_evidence,n.by annotation_by '
                 'FROM transactions t JOIN accounts a ON a.uid=t.account LEFT JOIN decisions d ON d.id=t.id '
                 'LEFT JOIN transaction_annotations n ON n.id=t.id WHERE 1=1')
        args = []
        if since: query += ' AND t.day>=?'; args.append(since)
        if until: query += ' AND t.day<?'; args.append(until)
        if undecided: query += ' AND d.id IS NULL'
        if not include_gone: query += ' AND t.gone IS NULL'
        with self.db() as db:
            return [dict(r) for r in db.execute(query + ' ORDER BY t.day DESC,t.first_seen DESC', args)]

    @staticmethod
    def _enqueue(db, kind, key, payload, now):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        existing = db.execute('SELECT payload FROM audit_jobs WHERE kind=? AND job_key=?', (kind, str(key))).fetchone()
        if existing:
            if existing['payload'] != encoded:
                raise ValueError('Audit job key already has different evidence')
            return
        db.execute('INSERT INTO audit_jobs(kind,job_key,payload,created,updated) VALUES(?,?,?,?,?)',
                   (kind, str(key), encoded, now, now))

    def enqueue(self, kind, key, payload):
        if kind not in ('transaction', 'owner_answer', 'question', 'explanation', 'enrichment'):
            raise ValueError('Unknown audit job kind')
        with self.db() as db:
            self._enqueue(db, kind, key, payload, self.clock())
            return db.execute('SELECT seq FROM audit_jobs WHERE kind=? AND job_key=?', (kind, str(key))).fetchone()[0]

    def bootstrap_jobs(self):
        """Bring undecided rows from a pre-queue live ledger into the durable queue."""
        with self.db() as db:
            now = self.clock()
            for row in db.execute('SELECT t.id FROM transactions t LEFT JOIN decisions d ON d.id=t.id '
                                  "WHERE (d.id IS NULL OR (d.by='ai' AND d.monthly_cents IS NULL)) "
                                  'AND t.gone IS NULL ORDER BY t.day,t.first_seen,t.id'):
                self._enqueue(db, 'transaction', row['id'], {'id': row['id']}, now)

    def jobs(self, state='pending', limit=80):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM audit_jobs WHERE state=? ORDER BY seq LIMIT ?', (state, limit))]

    def claim_jobs(self, limit=80, lease_seconds=1200, kind=None):
        """Fence one auditor call; a second caller cannot claim while its lease is live."""
        now, token = self.clock(), uuid.uuid4().hex
        with self.db() as db:
            state = db.execute('SELECT * FROM audit_state WHERE id=1').fetchone()
            if state['lease_token'] and state['lease_until'] > now:
                return None
            if state['lease_token'] and state['process_pid'] and _process_alive(state['process_pid']):
                return None
            db.execute("UPDATE audit_jobs SET state='pending',token=NULL WHERE state='running'")
            jobs = [dict(r) for r in db.execute("SELECT * FROM audit_jobs WHERE state='pending' " +
                    ("AND kind=? " if kind else "") + "ORDER BY seq LIMIT ?", (kind, limit) if kind else (limit,))]
            if not jobs:
                return None
            db.execute('UPDATE audit_state SET lease_token=?,lease_until=?,updated=?,process_pid=NULL WHERE id=1',
                       (token, now + lease_seconds, now))
            db.executemany("UPDATE audit_jobs SET state='running',token=?,attempts=attempts+1,updated=? WHERE seq=?",
                           [(token, now, job['seq']) for job in jobs])
            return token, jobs, state['session_id']

    def renew_claim(self, token, lease_seconds=1200):
        with self.db() as db:
            now = self.clock()
            db.execute('UPDATE audit_state SET lease_until=?,updated=? WHERE id=1 AND lease_token=? AND lease_until>?',
                       (now + lease_seconds, now, token, now))
            return bool(db.execute('SELECT changes()').fetchone()[0])

    def set_claim_process(self, token, pid):
        with self.db() as db:
            db.execute('UPDATE audit_state SET process_pid=? WHERE id=1 AND lease_token=? AND lease_until>?',
                       (pid, token, self.clock()))
            if not db.execute('SELECT changes()').fetchone()[0]:
                raise RuntimeError('Audit lease expired before process start')

    def finish_claim(self, token, jobs, session_id, decisions, insights, replies, category_ops=(), enrichments=()):
        with self.db() as db:
            state = db.execute('SELECT * FROM audit_state WHERE id=1').fetchone()
            if state['lease_token'] != token or state['lease_until'] <= self.clock():
                raise RuntimeError('Audit lease expired; response discarded')
            # Automatic follow-ups ("authority": "auto") are best effort; owner-requested batches are strict.
            explicit = [j for j in jobs if j['kind'] == 'enrichment' and json.loads(j['payload']).get('authority') != 'auto']
            if jobs and all(j['kind'] == 'enrichment' for j in jobs) and (decisions or category_ops):
                if explicit:
                    raise ValueError('Display enrichment cannot change accounting decisions')
                decisions, category_ops = [], []
            requested = {json.loads(j['payload'])['id'] for j in explicit}
            saved_by_tools = {r['id'] for r in db.execute(
                'SELECT id FROM transaction_annotations WHERE at>=?', (min((j['created'] for j in jobs), default=self.clock()),))}
            if requested - {item['id'] for item in enrichments} - saved_by_tools:
                raise ValueError('Auditor response omitted a requested enrichment')
            allowed_annotations = {json.loads(j['payload'])['id'] for j in jobs if j['kind'] in ('enrichment', 'transaction')}
            for item in enrichments:
                if item['id'] not in allowed_annotations:
                    raise ValueError('Unrequested transaction enrichment')
                self.annotate(item['id'], item, 'ai', db)
            answered = {r.get('job_seq') for r in replies if str(r.get('text') or '').strip()}
            if any(j['kind'] in ('question', 'explanation') and j['seq'] not in answered for j in jobs):
                raise ValueError('Auditor response omitted a requested reply')
            permitted = {json.loads(job['payload']).get('id') for job in jobs if job['kind'] == 'transaction'}
            reviews = {}
            for job in jobs:
                payload = json.loads(job['payload'])
                if job['kind'] == 'owner_answer' and payload.get('authority') == 'review_interpretation':
                    reviews[payload.get('id')] = payload
            decided_ids = {item['id'] for item in decisions}
            for identity, review in reviews.items():
                current = db.execute('SELECT * FROM decisions WHERE id=?', (identity,)).fetchone()
                if current and decision_version(current) == review.get('decision_version') and identity not in decided_ids:
                    raise ValueError('Auditor response omitted an owner review decision')
            # Category changes first, so decisions can use a category created in the same answer.
            for op in category_ops or ():
                try:
                    self.apply_category_op(op, 'ai', db)
                except (KeyError, ValueError):
                    continue  # an invalid suggestion never blocks the transaction decisions
            for item in decisions:
                self.ensure_category(item.get('category'), item['kind'], db)
                by = 'ai'
                review = reviews.get(item['id'])
                if review:
                    current = db.execute('SELECT * FROM decisions WHERE id=?', (item['id'],)).fetchone()
                    if not current or decision_version(current) != review.get('decision_version'):
                        continue  # A newer owner edit supersedes this review.
                    by = 'owner'
                elif item['id'] not in permitted:
                    # Revisions to older AI decisions are allowed, but owner decisions remain immutable.
                    row = db.execute('SELECT by FROM decisions WHERE id=?', (item['id'],)).fetchone()
                    if not row or row['by'] != 'ai':
                        continue
                self.decide(item['id'], item['kind'], item.get('category'), item['counts'], item.get('linked'),
                            item.get('reasoning'), item.get('confidence'), item.get('question'), by,
                            item.get('recurring'), item.get('monthly_cents'), item.get('coverage_months'),
                            item.get('series_key'), db, enqueue_owner=not bool(review))
            # Every transaction is enhanced the moment the auditor first sees it. One automatic follow-up is
            # queued for any it decided without an enhancement; the stable key means it is never queued twice.
            for job in jobs:
                identity = json.loads(job['payload']).get('id')
                if job['kind'] == 'transaction' and identity and not db.execute(
                        'SELECT 1 FROM transaction_annotations WHERE id=?', (identity,)).fetchone() and db.execute(
                        'SELECT 1 FROM transactions WHERE id=? AND gone IS NULL', (identity,)).fetchone():
                    self._enqueue(db, 'enrichment', 'auto:' + identity, {'id': identity, 'authority': 'auto'}, self.clock())
            for reply in replies:
                seq = reply.get('job_seq')
                if seq in {j['seq'] for j in jobs if j['kind'] in ('question', 'explanation')}:
                    db.execute('INSERT OR REPLACE INTO audit_outputs VALUES(?,?,?)',
                               (seq, str(reply.get('text') or ''), self.clock()))
            for job in jobs:
                db.execute("UPDATE audit_jobs SET state='done',token=NULL,updated=? WHERE seq=? AND token=?",
                           (self.clock(), job['seq'], token))
            if insights is not None and not all(j['kind'] == 'enrichment' for j in jobs):
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('insights', json.dumps(insights)))
            db.execute('UPDATE audit_state SET session_id=?,lease_token=NULL,lease_until=NULL,process_pid=NULL,updated=? WHERE id=1',
                       (session_id, self.clock()))

    def release_claim(self, token, session_id=None):
        with self.db() as db:
            state = db.execute('SELECT session_id FROM audit_state WHERE id=1 AND lease_token=?', (token,)).fetchone()
            if not state: return
            db.execute("UPDATE audit_jobs SET state='pending',token=NULL,updated=? WHERE token=?", (self.clock(), token))
            db.execute('UPDATE audit_state SET lease_token=NULL,lease_until=NULL,process_pid=NULL,session_id=?,updated=? WHERE id=1',
                       (session_id if session_id is not None else state['session_id'], self.clock()))

    def annotate(self, identity, item, by='owner', db=None):
        """Separate display metadata; bank records and accounting decisions are immutable here."""
        if db is None:
            with self.db() as connection:
                return self.annotate(identity, item, by, connection)
        if by not in ('owner', 'ai'):
            raise ValueError('Unknown annotation author')
        source = db.execute('SELECT counterparty,description FROM transactions WHERE id=?', (identity,)).fetchone()
        if not source:
            raise KeyError(identity)
        existing = db.execute('SELECT by FROM transaction_annotations WHERE id=?', (identity,)).fetchone()
        if existing and existing['by'] == 'owner' and by != 'owner':
            return False
        fields = {}
        for key, maximum in (('display_title', 140), ('merchant_name', 120), ('annotation_note', 1000), ('evidence', 1000)):
            value = item.get(key, '')
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError('Invalid annotation ' + key)
            fields[key] = value.strip()
        if not fields['display_title'] or not fields['evidence']:
            raise ValueError('Annotation needs a title and supporting evidence')
        tags = item.get('tags', [])
        confidence = item.get('confidence')
        if not isinstance(tags, list) or len(tags) > 12 or any(not isinstance(t, str) or not t.strip() or len(t) > 40 for t in tags):
            raise ValueError('Invalid annotation tags')
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError('Invalid annotation confidence')
        brand = item.get('merchant_brand_id') or None
        if brand and (not isinstance(brand, str) or brand not in BRAND_CATALOG or by == 'ai' and
                      (confidence < .85 or not supported_brand(brand, ' '.join(value or '' for value in source)))):
            raise ValueError('Brand identity lacks matching bank evidence')
        db.execute('INSERT OR REPLACE INTO transaction_annotations VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (identity, fields['display_title'], fields['merchant_name'], brand, fields['annotation_note'],
                    json.dumps(list(dict.fromkeys(t.strip() for t in tags)), ensure_ascii=False), confidence,
                    fields['evidence'], by, self.clock()))
        return True

    def audit_output(self, job_seq):
        with self.db() as db:
            row = db.execute('SELECT answer FROM audit_outputs WHERE job_seq=?', (job_seq,)).fetchone()
            return row['answer'] if row else None

    def decide(self, identity, kind, category, counts, linked, reasoning, confidence, question, by,
               recurring=UNSET, monthly_cents=UNSET, coverage_months=UNSET, series_key=UNSET, db=None,
               event_key=None, enqueue_owner=True):
        if kind not in KINDS:
            raise ValueError('Unknown kind %r' % kind)
        if monthly_cents not in (UNSET, None) and (not isinstance(monthly_cents, int) or monthly_cents < 0):
            raise ValueError('monthly_cents must be a nonnegative integer')
        months = list(coverage_months or []) if coverage_months is not UNSET else []
        if any(not isinstance(m, str) or len(m) != 7 or m[4] != '-' or not m[:4].isdigit() or not m[5:].isdigit()
               or not 1 <= int(m[5:]) <= 12 for m in months):
            raise ValueError('Invalid coverage month')
        if db is None:
            with self.db() as connection:
                return self.decide(identity, kind, category, counts, linked, reasoning, confidence, question, by,
                                   recurring, monthly_cents, coverage_months, series_key, connection, event_key, enqueue_owner)
        else:
            if not db.execute('SELECT 1 FROM transactions WHERE id=?', (identity,)).fetchone():
                raise KeyError(identity)
            current = db.execute('SELECT * FROM decisions WHERE id=?', (identity,)).fetchone()
            if current and current['by'] == 'owner' and by != 'owner':
                return False  # the owner's word stands
            if current:
                if recurring is UNSET: recurring = bool(current['recurring'])
                if monthly_cents is UNSET: monthly_cents = current['monthly_cents']
                if coverage_months is UNSET: months = json.loads(current['coverage_months'] or '[]')
                if series_key is UNSET: series_key = current['series_key']
            if recurring is UNSET: recurring = False
            if monthly_cents is UNSET: monthly_cents = None
            if series_key is UNSET: series_key = None
            self.ensure_category(category, kind, db)
            db.execute('INSERT OR REPLACE INTO decisions(id,kind,category,counts,linked,reasoning,confidence,question,by,at,'
                       'recurring,monthly_cents,coverage_months,series_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (identity, kind, category, int(bool(counts)), json.dumps(list(linked or [])), reasoning,
                        confidence, question or None, by, self.clock(), int(bool(recurring)), monthly_cents,
                        json.dumps(months), series_key))
            if by == 'owner' and enqueue_owner:
                fingerprint = hashlib.sha256(json.dumps([identity, kind, category, counts, linked, reasoning],
                                                      sort_keys=True).encode()).hexdigest()[:16]
                self._enqueue(db, 'owner_answer', event_key or 'decision:' + fingerprint,
                              {'id': identity, 'kind': kind, 'category': category, 'reasoning': reasoning}, self.clock())
        return True

    def categories(self):
        """The category catalogue with how often each is used; categories are budget envelopes."""
        with self.db() as db:
            return [dict(r) for r in db.execute("""SELECT c.*,COUNT(d.id) uses FROM categories c LEFT JOIN decisions d
                ON d.category=c.name GROUP BY c.name ORDER BY c.grp,c.name""")]

    def apply_category_op(self, op, by, db=None):
        """Create, update (or rename), merge or delete a category. The auditor never changes the owner's
        categories or budgets; renames and merges carry every transaction with them."""
        if db is None:
            with self.db() as connection:
                return self.apply_category_op(op, by, connection)
        kind, name = op.get('op'), (op.get('name') or '').strip()
        if not name or len(name) > 60:
            raise ValueError('A category needs a name of at most 60 characters.')
        group = op.get('group')
        if group is not None and group not in CATEGORY_GROUPS:
            raise ValueError('Unknown category group %r' % group)
        row = db.execute('SELECT * FROM categories WHERE name=?', (name,)).fetchone()
        if row and row['by'] == 'owner' and by != 'owner':
            return False
        now = self.clock()
        if kind == 'create' and not row:
            db.execute('INSERT INTO categories(name,emoji,grp,description,budget_cents,suggested_budget_cents,by,created,updated)'
                       ' VALUES(?,?,?,?,?,?,?,?,?)', (name, op.get('emoji'), group or 'elective', op.get('description') or '',
                       op.get('budget_cents') if by == 'owner' else None, op.get('suggested_budget_cents'), by, now, now))
            return True
        if kind in ('create', 'update'):
            if not row:
                raise KeyError(name)
            fields = {'emoji': op.get('emoji'), 'grp': group, 'description': op.get('description'),
                      'suggested_budget_cents': op.get('suggested_budget_cents')}
            if by == 'owner':
                fields.update(budget_cents=op.get('budget_cents'), by='owner')
            fields = {k: v for k, v in fields.items() if v is not None}
            new = (op.get('new_name') or '').strip()
            if new and new != name:
                if len(new) > 60 or db.execute('SELECT 1 FROM categories WHERE name=?', (new,)).fetchone():
                    raise ValueError('Category %r already exists; merge instead.' % new)
                db.execute('UPDATE categories SET name=? WHERE name=?', (new, name))
                db.execute('UPDATE decisions SET category=? WHERE category=?', (new, name))
                db.execute('UPDATE adjustments SET category=? WHERE category=?', (new, name))
                name = new
            if fields:
                db.execute('UPDATE categories SET %s,updated=? WHERE name=?' % ','.join(k + '=?' for k in fields),
                           list(fields.values()) + [now, name])
            return True
        if kind in ('merge', 'delete'):
            if not row:
                raise KeyError(name)
            into = (op.get('into') or '').strip()
            used = db.execute('SELECT COUNT(*) FROM decisions WHERE category=?', (name,)).fetchone()[0]
            if used and not into:
                raise ValueError('Category %r is in use; name a category to move its transactions into.' % name)
            if into:
                if into == name or not db.execute('SELECT 1 FROM categories WHERE name=?', (into,)).fetchone():
                    raise ValueError('Unknown target category %r' % into)
                db.execute('UPDATE decisions SET category=? WHERE category=?', (into, name))
                db.execute('UPDATE adjustments SET category=? WHERE category=?', (into, name))
            db.execute('DELETE FROM categories WHERE name=?', (name,))
            return True
        raise ValueError('Unknown category operation %r' % kind)

    def ensure_category(self, name, kind, db):
        if name and not db.execute('SELECT 1 FROM categories WHERE name=?', (name,)).fetchone():
            group = 'fixed' if kind == 'fixed_cost' else 'income' if kind in ('income', 'salary') else 'elective'
            db.execute('INSERT INTO categories(name,grp,created,updated) VALUES(?,?,?,?)', (name, group, self.clock(), self.clock()))

    def corrections(self, limit=60):
        query = ('SELECT t.id,t.day,t.amount_cents,t.counterparty,t.description,a.bank,d.kind,d.category,d.counts,d.reasoning,'
                 'd.recurring,d.monthly_cents,d.coverage_months,d.series_key FROM decisions d '
                 'JOIN transactions t ON t.id=d.id JOIN accounts a ON a.uid=t.account WHERE d.by=\'owner\' ORDER BY d.at DESC LIMIT ?')
        with self.db() as db:
            return [dict(r) for r in db.execute(query, (limit,))]

    def add_adjustment(self, identity, day, kind, amount_cents, category, linked, reason, source):
        """Owner-confirmed off-bank offset; never inserted into bank transactions."""
        if kind not in ('shared_cost_offset', 'cash_offset') or amount_cents <= 0 or not source or not reason:
            raise ValueError('An offset needs a kind, positive cents, reason and source')
        date.fromisoformat(day)
        values = (identity, day, kind, amount_cents, category, json.dumps(list(linked)), reason, source)
        with self.db() as db:
            existing = db.execute('SELECT id,day,kind,amount_cents,category,linked,reason,source FROM adjustments WHERE id=?',
                                  (identity,)).fetchone()
            if existing:
                if tuple(existing) != values:
                    raise ValueError('Offset ID already has different evidence')
                return False
            db.execute('INSERT INTO adjustments VALUES(?,?,?,?,?,?,?,?,?)', (*values, self.clock()))
            return True

    def adjustments(self, since=None, until=None):
        query, args = 'SELECT * FROM adjustments WHERE 1=1', []
        if since: query += ' AND day>=?'; args.append(since)
        if until: query += ' AND day<?'; args.append(until)
        with self.db() as db:
            return [dict(r) for r in db.execute(query + ' ORDER BY day,id', args)]


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
    history = ledger.transactions(until=end.isoformat())
    adjustments = ledger.adjustments(start.isoformat(), end.isoformat())
    counted = [r for r in rows if r['kind'] and r['counts']]
    real = [r for r in rows if r['kind'] and r['kind'] not in ('internal_transfer', 'duplicate')]
    profiles = {}
    for row in sorted(history, key=lambda r: (r['day'] or '', r['decided'] or 0, r['id'])):
        if row['kind'] in ('income', 'salary') and row['amount_cents'] > 0:
            direction = 'income'
        elif row['kind'] in RECURRING_COST_KINDS and row['amount_cents'] < 0:
            direction = 'cost'
        else:
            continue
        key = row['series_key'] or ':'.join((direction, row['bank'], row['counterparty'] or row['category'] or row['id']))
        if not row['recurring'] or row['monthly_cents'] is None:
            if row['series_key']:
                profiles.pop((direction, key), None)
            continue
        profiles[(direction, key)] = {'key': key, 'category': row['category'] or row['counterparty'] or 'Other',
                                      'monthly_cents': row['monthly_cents'], 'source_id': row['id'],
                                      'kind': row['kind'], 'coverage_months': json.loads(row['coverage_months'] or '[]'),
                                      'confidence': row['confidence'], 'source_day': row['day']}
    regular_income = sum(p['monthly_cents'] for (direction, _), p in profiles.items() if direction == 'income')
    recurring_costs = sum(p['monthly_cents'] for (direction, _), p in profiles.items() if direction == 'cost')
    free = max(0, regular_income - recurring_costs)
    # The existing CLI writes amount_cents without a mode; that action is a manual pin.
    pinned = 'amount_cents' in allowance
    budget = allowance.get('amount_cents', 0) if pinned else free
    spent = -sum(r['amount_cents'] for r in counted) - sum(a['amount_cents'] for a in adjustments)
    remaining = budget - spent
    days_total, days_left = (end - start).days, (end - today).days
    elapsed = days_total - days_left + 1
    categories, category_transactions, fixed = {}, {}, {}
    for r in rows:
        if r['kind'] not in ('expense', 'fixed_cost', 'cash_withdrawal', 'fee', 'reimbursement', 'refund'):
            continue
        category = r['category'] or 'Other'
        categories[category] = categories.get(category, 0) - r['amount_cents']
        category_transactions.setdefault(category, []).append(public(r))
        if r['kind'] == 'fixed_cost' and r['amount_cents'] < 0:
            fixed[category] = fixed.get(category, 0) - r['amount_cents']
    for adjustment in adjustments:
        category = adjustment['category'] or 'Other'
        categories[category] = categories.get(category, 0) - adjustment['amount_cents']
        category_transactions.setdefault(category, []).append({
            'id': adjustment['id'], 'record_type': 'off_bank_offset', 'day': adjustment['day'],
            'amount_cents': adjustment['amount_cents'], 'category': category,
            'reasoning': adjustment['reason'], 'linked': json.loads(adjustment['linked'])})
    profile_rows = sorted(profiles.values(), key=lambda p: (p['kind'], p['category'], p['key']))
    # Which months each regular income has arrived for; transfers covering several months fill each of them.
    tracker, current = [], today.strftime('%Y-%m')
    for (direction, key), profile in sorted(profiles.items()):
        if direction != 'income':
            continue
        received = {}
        for r in history:
            if r['series_key'] == key and r['amount_cents'] > 0:
                months = json.loads(r['coverage_months'] or '[]') or [(r['day'] or current)[:7]]
                for m in months:
                    received[m] = received.get(m, 0) + r['amount_cents'] // len(months)
        first = min(received) if received else current
        year, month, months = int(first[:4]), int(first[5:]), []
        while '%04d-%02d' % (year, month) <= current:
            m = '%04d-%02d' % (year, month)
            months.append({'month': m, 'received': m in received, 'amount_cents': received.get(m, 0)})
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        tracker.append({'key': key, 'name': profile['category'], 'monthly_cents': profile['monthly_cents'], 'months': months[-6:]})
    actual_recurring = sum(r['amount_cents'] for r in real if r['recurring'] and r['monthly_cents'] is not None
                           and ((r['kind'] in ('income', 'salary') and r['amount_cents'] > 0)
                                or (r['kind'] in RECURRING_COST_KINDS and r['amount_cents'] < 0)))
    cash_net = sum(r['amount_cents'] for r in real)
    offset_total = sum(a['amount_cents'] for a in adjustments)
    review = [r for r in rows if r['kind'] and r['question']]
    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat(), 'days_left': days_left, 'days_total': days_total},
        'allowance': {**allowance, 'amount_cents': budget, 'mode': 'pinned' if pinned else 'auto'},
        'regular_income_cents': regular_income, 'recurring_costs_cents': recurring_costs,
        'free_to_spend_cents': free, 'spent_cents': spent, 'remaining_cents': remaining,
        'safe_per_day_cents': max(0, remaining) // max(1, days_left),
        'expected_cents': budget * elapsed // days_total,
        'income_cents': sum(r['amount_cents'] for r in real if r['amount_cents'] > 0),
        'outgoing_cents': -sum(r['amount_cents'] for r in real if r['amount_cents'] < 0),
        'net_cents': cash_net, 'payday_aware_net_cents': cash_net - actual_recurring + regular_income - recurring_costs + offset_total,
        'off_bank_offsets_cents': offset_total,
        'undecided': sum(1 for r in rows if not r['kind']),
        'decided': sum(1 for r in rows if r['kind']),
        'categories': sorted(({'name': k, 'cents': v} for k, v in categories.items()), key=lambda c: -c['cents']),
        'category_transactions': category_transactions,
        'fixed_costs': sorted(({'name': k, 'cents': v} for k, v in fixed.items()), key=lambda c: -c['cents']),
        'fixed_cost_transactions': [public(r) for r in rows if r['kind'] == 'fixed_cost'],
        'recurring_breakdown': profile_rows,
        'income_tracker': tracker,
        'category_catalog': [{k: c[k] for k in ('name', 'emoji', 'grp', 'description', 'budget_cents', 'suggested_budget_cents', 'by')}
                             for c in ledger.categories()],
        'adjustments': [{k: a[k] for k in ('id', 'day', 'kind', 'amount_cents', 'category', 'reason', 'source')}
                        | {'linked': json.loads(a['linked'])} for a in adjustments],
        'review': [public(r) for r in review],
        'transactions': [public(r) for r in rows[:200]],
        'insights': insights if insights is not None else ledger.setting('insights') or [],
        'banks': [{'bank': b['bank'], 'valid_until': (b['valid_until'] or '')[:10] or None} for b in ledger.banks()],
    }


def public(row):
    row = dict(row)
    return {k: row[k] for k in ('id', 'bank', 'status', 'day', 'amount_cents', 'currency', 'counterparty', 'description', 'kind',
                                'category', 'counts', 'reasoning', 'confidence', 'question', 'by', 'recurring',
                                'monthly_cents', 'series_key')} | {'linked': json.loads(row['linked'] or '[]'),
                                                                  'coverage_months': json.loads(row['coverage_months'] or '[]')} | annotation_public(row)


def annotation_public(row):
    row = dict(row)
    return {'display_title': row.get('display_title') or row.get('counterparty') or row.get('description') or 'Transaction',
            'merchant_name': row.get('merchant_name') or '', 'merchant_brand_id': row.get('merchant_brand_id'),
            'annotation_note': row.get('annotation_note') or '', 'tags': json.loads(row.get('annotation_tags') or '[]'),
            'annotation_confidence': row.get('annotation_confidence'),
            'annotation_evidence': row.get('annotation_evidence') or '', 'annotation_by': row.get('annotation_by')}
