"""Idempotent statement backfill with per-row provenance and live-feed overlap matching.

Extraction and financial interpretation are separate: this module stores evidence,
preserves decisions, and never invents a category or a reimbursement.
"""
from datetime import date
from difflib import SequenceMatcher
import hashlib
import json
import re
import unicodedata

from .ledger import normalise


def _schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS statement_rows(
        account TEXT NOT NULL,source_key TEXT NOT NULL,transaction_id TEXT NOT NULL,
        source_hash TEXT NOT NULL,source_path TEXT NOT NULL,page INTEGER NOT NULL,
        evidence TEXT NOT NULL,PRIMARY KEY(account,source_hash,source_key))''')
    db.execute('''CREATE TABLE IF NOT EXISTS statement_provider_aliases(
        account TEXT NOT NULL,provider_id TEXT NOT NULL,transaction_id TEXT NOT NULL,
        PRIMARY KEY(account,provider_id))''')


def _text(value):
    value = unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode().lower()
    value = re.sub(r'[^a-z0-9]', '', value)
    for word in ('verwendungszweckkundenreferenz','abrechnungkarte','kartenzahlung'):
        value = value.replace(word, '')
    return value


def _evidence(row):
    return _text((row.get('counterparty') or '') + ' ' + (row.get('description') or ''))


def _similarity(left, right):
    a,b = _evidence(left),_evidence(right)
    if not a or not b:
        return 0.0
    if min(len(a),len(b)) >= 7 and (a in b or b in a):
        return 1.0
    # Statement labels are often short, while the feed has the original merchant
    # field; compare each field as well as the complete remittance text.
    values = [SequenceMatcher(None,a,b).ratio()]
    for first in ('counterparty','description'):
        for second in ('counterparty','description'):
            x,y = _text(left.get(first)),_text(right.get(second))
            if min(len(x),len(y)) >= 4 and x not in ('bank','card','sepa') and y not in ('bank','card','sepa'):
                values.append(1.0 if x in y or y in x else SequenceMatcher(None,x,y).ratio())
    return max(values)


def _match_all(rows, existing, max_days=7):
    """One-to-one matching; exact unique amount/day is resolved before fuzzy dates.

    Same-day collisions require merchant evidence. Ambiguous equal-scored matches
    remain unmatched for explicit review rather than collapsing real payments.
    """
    matches,used = {},set()
    for window in (0,max_days):
        progress = True
        while progress:
            progress = False
            for index,row in enumerate(rows):
                if index in matches:
                    continue
                candidates=[]
                for known in existing:
                    if known['id'] in used or known['amount_cents'] != row['amount_cents'] or known['currency'] != row.get('currency','EUR'):
                        continue
                    dates=[known['day']]
                    if window:
                        raw=json.loads(known.get('raw') or '{}')
                        dates.extend(raw[k] for k in ('value_date','transaction_date') if raw.get(k))
                    gap=min(abs((date.fromisoformat(row['day'])-date.fromisoformat(day)).days) for day in dates)
                    if gap>window:
                        continue
                    similarity=_similarity(row,known)
                    if similarity < (.72 if gap else .65):
                        continue
                    candidates.append((similarity-gap*.015,known['id']))
                candidates.sort(reverse=True)
                if not candidates:
                    continue
                score,identity=candidates[0]
                if len(candidates)>1 and (score<.72 or score-candidates[1][0]<.025):
                    tied=[k for k in existing if k['id'] in {x[1] for x in candidates if score-x[0]<.025}]
                    same_evidence=len({_evidence(k) for k in tied})==1
                    if score<.95 or not same_evidence:continue
                matches[index]=identity;used.add(identity);progress=True
    return matches


def import_rows(ledger, account, rows, *, enqueue=True):
    """Backfill extracted booked rows, retaining original provider IDs/decisions.

    A caller must verify source balances before committing. Every source row needs
    a stable source_key (including an occurrence ordinal for repeated payments).
    """
    rows=list(rows)
    if len({(r['source_hash'],r['source_key']) for r in rows})!=len(rows):
        raise ValueError('Source keys must distinguish repeated real transactions')
    for row in rows:
        date.fromisoformat(row['day'])
        if not isinstance(row['amount_cents'],int) or row.get('currency','EUR')!='EUR' or not re.fullmatch(r'[a-f0-9]{64}',row['source_hash']):
            raise ValueError('Invalid extracted amount, currency or source hash')
    now=ledger.clock();report={'inserted':0,'matched':0,'already_imported':0,'rows':[],'unmatched_in_overlap':[]}
    with ledger.db() as db:
        _schema(db)
        if not db.execute('SELECT 1 FROM accounts WHERE uid=?',(account,)).fetchone():
            raise ValueError('Unknown account')
        existing=[dict(r) for r in db.execute("SELECT * FROM transactions WHERE account=? AND gone IS NULL AND status='booked'",(account,))]
        new=[]
        for row in rows:
            saved=db.execute('SELECT transaction_id FROM statement_rows WHERE account=? AND source_hash=? AND source_key=?',(account,row['source_hash'],row['source_key'])).fetchone()
            if saved:
                report['already_imported']+=1;report['rows'].append({'source_key':row['source_key'],'id':saved['transaction_id'],'action':'existing'})
            else:new.append(row)
        matches=_match_all(new,existing)
        earliest=min((r['day'] for r in existing),default='9999')
        for index,row in enumerate(new):
            identity=matches.get(index)
            if identity:
                report['matched']+=1;action='matched'
            else:
                token=hashlib.sha256(json.dumps([row['day'],row['amount_cents'],row.get('counterparty'),row.get('description'),row['source_key']],ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:28]
                identity=account+':statement:'+token
                raw=json.dumps({'statement_import':True,**row},ensure_ascii=False,sort_keys=True)
                known=db.execute('SELECT 1 FROM transactions WHERE id=?',(identity,)).fetchone()
                if not known:
                    db.execute('INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)',(identity,account,'booked',row['day'],row['amount_cents'],'EUR',row.get('counterparty',''),row.get('counterparty_iban',''),row.get('description',''),raw,now,now))
                    if enqueue:ledger._enqueue(db,'transaction',identity,{'id':identity},now)
                    report['inserted']+=1
                action='inserted'
                if row['day']>=earliest:report['unmatched_in_overlap'].append(identity)
            db.execute('INSERT INTO statement_rows VALUES(?,?,?,?,?,?,?)',(account,row['source_key'],identity,row['source_hash'],row['source'],row['page'],json.dumps(row,ensure_ascii=False,sort_keys=True)))
            report['rows'].append({'source_key':row['source_key'],'id':identity,'action':action})
    return report


def coalesce_provider_rows(ledger, account, raws):
    """Keep a statement ID if a later feed first supplies that booked payment.

    Stable aliases preserve exact provider identity on all subsequent syncs. The
    original reference remains in raw provenance even when its canonical ID is the
    earlier statement row. Pending rows use the normal feed lifecycle unchanged.
    """
    raws=[dict(r) for r in raws]
    with ledger.db() as db:
        _schema(db)
        aliases={r['provider_id']:r['transaction_id'] for r in db.execute('SELECT * FROM statement_provider_aliases WHERE account=?',(account,))}
        statement=[dict(r) for r in db.execute("SELECT * FROM transactions WHERE account=? AND id LIKE ? AND gone IS NULL",(account,account+':statement:%'))]
        claimed=set(aliases.values())
        pending=[];positions=[]
        for index,raw in enumerate(raws):
            row=normalise(account,raw)
            if row['status']=='pending':continue
            if row['id'] in aliases:
                raws[index]['statement_provider_reference']=raw.get('entry_reference') or raw.get('transaction_id')
                raws[index]['entry_reference']=aliases[row['id']][len(account)+1:]
            elif not db.execute('SELECT 1 FROM transactions WHERE id=?',(row['id'],)).fetchone():
                pending.append(row);positions.append(index)
        matches=_match_all(pending,[r for r in statement if r['id'] not in claimed])
        for index,identity in matches.items():
            row=pending[index];position=positions[index]
            db.execute('INSERT OR IGNORE INTO statement_provider_aliases VALUES(?,?,?)',(account,row['id'],identity))
            raws[position]['statement_provider_reference']=raws[position].get('entry_reference') or raws[position].get('transaction_id')
            raws[position]['entry_reference']=identity[len(account)+1:]
    return raws
