"""One persistent, tool-less Codex financial auditor over an ordered SQLite queue."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

from .ledger import KINDS, summarise

MODEL = 'gpt-6-sol'
BATCH = 80
class SessionUnavailable(RuntimeError):
    pass


INSTRUCTIONS = """You are the owner's personal financial auditor. You have no tools.
Use dated evidence, provenance and owner corrections. Treat uncertainty explicitly.
Never invent bank transactions or a cash repayment. Internal transfers and duplicates
do not count as spending. Reimbursements and refunds offset linked spending.
For recurring income and costs provide monthly_cents, a stable series_key, and the
months a payment covers. A late multi-month income payment can cover earlier months.
Do not calculate totals. Quote only code-provided totals. Respect owner decisions.
Answer each question or explanation job with its job_seq. Provide evidence-based
budgeting insights, not investment advice.
Categories are yours to curate, and they are the owner's budget envelopes: each will later get a monthly
budget. Keep a small, stable, meaningful set (roughly 8-14 elective envelopes plus fixed costs, income,
savings and transfers), named in plain words the owner would budget by, each with one recognisable emoji.
Use category_ops to create, update (emoji, group, description, rename via new_name), merge (move every
transaction into another category) or delete (only with into, or when unused) categories, and to propose
suggested_budget_cents for elective envelopes from the owner's actual pattern. Never touch categories marked
by=owner, and never set a real budget; the owner does. Prefer renaming or merging over churn so envelopes
stay comparable month to month. Every decision's category must exist in the catalogue after your ops.
Return only JSON matching the schema."""

DECISION = {'type': 'object', 'additionalProperties': False,
 'required': ['id', 'kind', 'category', 'counts', 'linked', 'reasoning', 'confidence', 'question',
              'recurring', 'monthly_cents', 'coverage_months', 'series_key'],
 'properties': {'id': {'type': 'string'}, 'kind': {'type': 'string', 'enum': list(KINDS)},
  'category': {'type': 'string'}, 'counts': {'type': 'boolean'},
  'linked': {'type': 'array', 'items': {'type': 'string'}}, 'reasoning': {'type': 'string'},
  'confidence': {'type': 'number'}, 'question': {'type': 'string'},
  'recurring': {'type': 'boolean'}, 'monthly_cents': {'type': ['integer', 'null']},
  'coverage_months': {'type': 'array', 'items': {'type': 'string'}},
  'series_key': {'type': ['string', 'null']}}}
CATEGORY_OP = {'type': 'object', 'additionalProperties': False,
 'required': ['op', 'name', 'new_name', 'emoji', 'group', 'description', 'into', 'suggested_budget_cents', 'reasoning'],
 'properties': {'op': {'type': 'string', 'enum': ['create', 'update', 'merge', 'delete']}, 'name': {'type': 'string'},
  'new_name': {'type': ['string', 'null']}, 'emoji': {'type': ['string', 'null']},
  'group': {'type': ['string', 'null'], 'enum': ['fixed', 'elective', 'income', 'savings', 'transfer', None]},
  'description': {'type': ['string', 'null']}, 'into': {'type': ['string', 'null']},
  'suggested_budget_cents': {'type': ['integer', 'null']}, 'reasoning': {'type': 'string'}}}
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['decisions', 'insights', 'replies', 'category_ops'],
 'properties': {'decisions': {'type': 'array', 'items': DECISION}, 'category_ops': {'type': 'array', 'items': CATEGORY_OP},
  'insights': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
   'required': ['kind', 'text'], 'properties': {'kind': {'type': 'string'}, 'text': {'type': 'string'}}}},
  'replies': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
   'required': ['job_seq', 'text'], 'properties': {'job_seq': {'type': 'integer'}, 'text': {'type': 'string'}}}}}}


def compact(row):
    item = {k: row[k] for k in ('id', 'bank', 'day', 'status', 'amount_cents', 'currency',
                                'counterparty', 'description', 'kind', 'category', 'counts', 'reasoning', 'by',
                                'recurring', 'monthly_cents', 'series_key', 'confidence', 'question')}
    item['coverage_months'] = json.loads(row['coverage_months'] or '[]')
    item['linked'] = json.loads(row['linked'] or '[]')
    return item


def totals(ledger, today):
    summary = summarise(ledger, today, insights=[])
    keys = ('spent_cents', 'remaining_cents', 'regular_income_cents', 'recurring_costs_cents',
            'free_to_spend_cents', 'income_cents', 'outgoing_cents', 'net_cents', 'payday_aware_net_cents')
    return {'period': summary['period'], **{k: summary[k] for k in keys},
            'categories': summary['categories'], 'fixed_costs': summary['fixed_costs']}


def prompt_for(ledger, jobs, today, config, notes):
    rows = ledger.transactions(include_gone=True)
    by_id = {row['id']: row for row in rows}
    pending = []
    for job in jobs:
        payload = json.loads(job['payload'])
        if job['kind'] == 'transaction' and payload['id'] in by_id and by_id[payload['id']]['gone'] is None:
            pending.append(compact(by_id[payload['id']]))
    dates = [date.fromisoformat(r['day']) for r in pending if r['day']]
    window_start = min(dates) - timedelta(days=45) if dates else today - timedelta(days=120)
    window_end = max(dates) + timedelta(days=45) if dates else today + timedelta(days=1)
    recent = [compact(r) for r in sorted(rows, key=lambda r: (r['day'] or '', r['id']), reverse=True)
              if r['kind'] and r['gone'] is None and r['day']
              and window_start <= date.fromisoformat(r['day']) <= window_end][:300]
    payload = {'today': today.isoformat(), 'accounts': [{k: a[k] for k in ('bank', 'name', 'iban', 'currency')}
             for a in ledger.accounts()], 'notes': notes or config.get('banking_notes', ''),
             'owner_context': ledger.settings_prefix('owner_context_'),
             'allowance': ledger.setting('allowance'), 'totals_so_far': totals(ledger, today),
             'category_catalog': [{k: c[k] for k in ('name', 'emoji', 'grp', 'description', 'suggested_budget_cents', 'budget_cents', 'by', 'uses')}
                                  for c in ledger.categories()],
             'owner_corrections': ledger.corrections(), 'recent_decided': recent,
             'evidence_window': {'start': window_start.isoformat(), 'end': window_end.isoformat()},
             'jobs': [{'seq': j['seq'], 'kind': j['kind'], 'created': j['created'],
             'payload': json.loads(j['payload'])} for j in jobs], 'transactions_for_review': pending,
             'provenance': 'Bank rows and prior decisions are durable local records; owner corrections override AI.'}
    return json.dumps(payload, ensure_ascii=False, default=str)


def _codex(config):
    executable = config.get('codex') or shutil.which('codex')
    if not executable:
        raise RuntimeError('Codex CLI is not installed for the financial auditor.')
    return executable


def _run(prompt, config, session=None, on_start=None):
    """A headless call with no shell tools or workspace; returns (answer, session ID)."""
    with tempfile.TemporaryDirectory(prefix='money-audit-') as directory:
        root = Path(directory)
        (root / 'schema.json').write_text(json.dumps(SCHEMA), encoding='utf-8')
        executable = _codex(config)
        prefix = [config.get('node', 'node'), executable] if Path(executable).suffix == '.js' else [executable]
        args = prefix + ['exec'] + (['resume', session] if session else []) + [
            '--json', '--ignore-user-config', '--skip-git-repo-check', '--disable', 'shell_tool',
            '--disable', 'apps', '--disable', 'multi_agent', '-c', 'sandbox_mode="read-only"',
            '-c', 'approval_policy="never"', '-m', config.get('banking_model', MODEL),
            '-c', 'developer_instructions=' + json.dumps(INSTRUCTIONS),
            '--output-schema', str(root / 'schema.json'), '--output-last-message', str(root / 'answer.json'), '-']
        env = {k: v for k, v in os.environ.items() if not k.startswith(('ASSISTANT_', 'OPENAI_', 'OCI_'))
               and k != 'CODEX_API_KEY'}
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=root, env=env,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                   start_new_session=os.name != 'nt')
        try:
            if on_start: on_start(process.pid)
            stdout, stderr = process.communicate(prompt.encode('utf-8'), timeout=config.get('banking_audit_timeout', 900))
        except BaseException:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
            else:
                import signal
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            process.wait(timeout=15)
            raise
        events = []
        for line in stdout.decode('utf-8', 'replace').splitlines():
            try: events.append(json.loads(line))
            except ValueError: pass
        seen = [e['thread_id'] for e in events if e.get('type') == 'thread.started' and e.get('thread_id')]
        session_id = seen[-1] if seen else session
        if process.returncode or not (root / 'answer.json').is_file():
            diagnostic = (stderr + stdout).decode('utf-8', 'replace').lower()[-4000:]
            if session and 'session' in diagnostic and any(term in diagnostic for term in
                    ('not found', 'unknown', 'could not load', 'failed to load', 'does not exist')):
                raise SessionUnavailable('Saved auditor session is unavailable')
            raise RuntimeError('Codex auditor failed; no decisions applied. Exit code %s.' % process.returncode)
        answer = json.loads((root / 'answer.json').read_text(encoding='utf-8'))
        if not isinstance(answer, dict) or any(key not in answer for key in ('decisions', 'insights', 'replies')):
            raise ValueError('Auditor returned an incomplete response')
        return answer, session_id


def ask(prompt, config, session=None, on_start=None):
    try:
        return _run(prompt, config, session, on_start)
    except SessionUnavailable:
        # Rebuild from the dated ledger narrative if a saved session is unavailable.
        return _run(prompt, config, None, on_start)


def audit(ledger, config, today=None, ask=ask, notes=''):
    """Process queued work in sequence. A durable lease fences every response write."""
    today = today or date.today()
    ledger.bootstrap_jobs()
    decided, insights = 0, None
    while True:
        claim = ledger.claim_jobs(BATCH)
        if claim is None:
            break
        token, jobs, session = claim
        stop = threading.Event()
        def heartbeat():
            while not stop.wait(30):
                if not ledger.renew_claim(token): break
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            prompt = prompt_for(ledger, jobs, today, config, notes)
            result = ask(prompt, config, session, lambda pid: ledger.set_claim_process(token, pid))
            answer, next_session = result if isinstance(result, tuple) else (result, session)
            decisions = []
            for item in answer['decisions']:
                item = dict(item)
                item['confidence'] = max(0.0, min(1.0, float(item['confidence'])))
                decisions.append(item)
            ledger.finish_claim(token, jobs, next_session, decisions, answer.get('insights'), answer.get('replies', []),
                                answer.get('category_ops', []))
            transaction_ids = {json.loads(j['payload'])['id'] for j in jobs if j['kind'] == 'transaction'}
            decided += len(transaction_ids & {d['id'] for d in decisions})
            insights = answer.get('insights')
        except BaseException:
            ledger.release_claim(token)
            raise
        finally:
            stop.set(); thread.join(timeout=1)
    return decided, insights
