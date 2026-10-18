"""AI auditor: decides what each transaction is and draws the month's conclusions.

The model sees the owner's accounts, the allowance definition, the owner's past corrections,
recent decided history and the undecided transactions. It returns a decision per transaction,
with reasoning and confidence, and a few insights. It may revise its own earlier decisions when
new evidence arrives (a reimbursement days after a dinner), never the owner's.
"""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .ledger import KINDS, summarise

MODEL = 'claude-sonnet-5-5'
BATCH = 80

INSTRUCTIONS = '''You are the owner's personal finance auditor. You read their own bank transactions and decide
what each one really is. Nobody pre-programmed rules for you; use judgement, evidence and the owner's past corrections.

Context about how the owner uses their accounts is in "accounts" and "notes". Typical patterns to recognise:
- Internal transfers between the owner's own accounts (for example a main-bank top-up to a card account). Both legs
  are "internal_transfer", counts=false, linked to each other. They are not spending or income.
- Money back from friends for something the owner paid (a shared dinner): "reimbursement", counts=true, linked to the
  original payment, so the net cost is what counts. Payments to friends that are loans: "lent", counts=false.
  Friends paying a loan back: "repaid_to_me", counts=false.
- Merchant refunds: "refund", counts=true, linked to the purchase.
- The same charge seen twice (pending and booked under different references, or on both accounts): "duplicate" for
  the redundant copy, counts=false, linked to the kept one.
- Fixed costs (rent, utilities, insurance, phone, debt payments): "fixed_cost". Whether they count against the
  allowance follows the allowance definition.
- Salary "salary"; other income "income"; transfers to savings "savings"; bank fees "fee";
  ATM cash "cash_withdrawal" (counts as spending); ordinary purchases "expense".
counts=true means the amount (negative spend or positive offset) is summed against the allowance.
Give a short human category for anything that counts (Groceries, Eating out, Transport, Cash, Subscriptions, ...).
Reasoning: one plain sentence citing the evidence (amounts, dates, names). Confidence 0..1.
When you are not confident enough to act on the owner's behalf (below about 0.75), still give your best decision
and add a short question the owner can answer with one tap. Otherwise question is "".
You may return decisions for the "recent" transactions too, but only to change one in the light of new evidence.
Insights: at most 5 short, specific, actionable observations about this period (pace against the allowance, money
still owed by friends, new or price-changed subscriptions, unusual charges, fees). Budgeting information only, never
investment advice. Write amounts in euros like €12.50. Quote totals only from "totals_so_far" (computed by code
before this batch's decisions); never add up amounts yourself.'''

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['decisions', 'insights'], 'properties': {
    'decisions': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
        'required': ['id', 'kind', 'category', 'counts', 'linked', 'reasoning', 'confidence', 'question'], 'properties': {
            'id': {'type': 'string'}, 'kind': {'type': 'string', 'enum': list(KINDS)}, 'category': {'type': 'string'},
            'counts': {'type': 'boolean'}, 'linked': {'type': 'array', 'items': {'type': 'string'}},
            'reasoning': {'type': 'string'}, 'confidence': {'type': 'number'}, 'question': {'type': 'string'}}}},
    'insights': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'text'],
        'properties': {'kind': {'type': 'string', 'enum': ['pace', 'owed', 'subscription', 'anomaly', 'fee', 'savings', 'other']},
                       'text': {'type': 'string'}}}}}}


def compact(row):
    item = {'id': row['id'], 'bank': row['bank'], 'day': row['day'], 'status': row['status'],
            'amount': '%.2f' % (row['amount_cents'] / 100), 'currency': row['currency'],
            'counterparty': row['counterparty'], 'description': row['description'][:200]}
    if row.get('counterparty_iban'): item['counterparty_iban'] = row['counterparty_iban']
    if row.get('kind'):
        item['decision'] = {'kind': row['kind'], 'category': row['category'], 'counts': bool(row['counts']),
                            'linked': json.loads(row['linked'] or '[]'), 'by': row['by']}
    return item


def totals(ledger, today):
    """The code's own arithmetic for this period, so insights quote these figures instead of estimating."""
    s = summarise(ledger, today, insights=[])
    euros = lambda c: '%.2f' % (c / 100)
    return {'period': s['period'], 'allowance_spent': euros(s['spent_cents']), 'allowance_left': euros(s['remaining_cents']),
            'safe_per_day': euros(s['safe_per_day_cents']), 'straight_line_spend_by_today': euros(s['expected_cents']),
            'income': euros(s['income_cents']), 'outgoing': euros(s['outgoing_cents']), 'net': euros(s['net_cents']),
            'categories': {c['name']: euros(c['cents']) for c in s['categories']}}


def claude(config):
    from personal_assistant.orchestrator.capacity import claude_executable
    executable = claude_executable(config)
    if not executable:
        raise RuntimeError('Claude Code is not installed for the assistant.')
    return executable


def ask(prompt, config):
    """One headless, tool-less model call returning the structured answer."""
    args = [claude(config), '-p', '--output-format', 'json', '--model', config.get('banking_model', MODEL), '--tools', '',
            '--strict-mcp-config', '--no-session-persistence', '--json-schema', json.dumps(SCHEMA),
            '--append-system-prompt', INSTRUCTIONS]
    environment = {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY' and not k.startswith(('CLAUDECODE', 'CLAUDE_CODE_'))}
    with tempfile.TemporaryDirectory() as empty:
        done = subprocess.run(args, input=prompt.encode(), capture_output=True, cwd=empty, env=environment, timeout=900,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if done.returncode:
        raise RuntimeError('Model call failed: %s' % done.stderr.decode('utf-8', 'replace')[-400:])
    result = json.loads(done.stdout)
    if result.get('is_error') or not isinstance(result.get('structured_output'), dict):
        raise RuntimeError('Model gave no structured answer.')
    return result['structured_output']


def audit(ledger, config, today=None, ask=ask, notes=''):
    """Decides every undecided transaction, in batches. Returns (decided, insights)."""
    today = today or date.today()
    accounts = [{'bank': a['bank'], 'name': a['name'], 'iban': a['iban'], 'currency': a['currency']} for a in ledger.accounts()]
    allowance = ledger.setting('allowance')
    decided, insights = 0, None
    while True:
        pending = sorted(ledger.transactions(undecided=True), key=lambda r: (r['day'] or '', r['id']))[:BATCH]
        if not pending:
            break
        oldest = min(r['day'] or today.isoformat() for r in pending)
        window = (date.fromisoformat(oldest) - timedelta(days=21)).isoformat()
        ids = {r['id'] for r in pending}
        recent = [compact(r) for r in ledger.transactions(since=window) if r['kind'] and r['id'] not in ids][:300]
        prompt = json.dumps({'today': today.isoformat(), 'accounts': accounts, 'notes': notes or config.get('banking_notes', ''),
            'allowance': {'amount': '%.2f' % (allowance['amount_cents'] / 100), 'currency': allowance['currency'],
                          'period': allowance['period'], 'definition': allowance['definition']},
            'totals_so_far': totals(ledger, today), 'owner_corrections': ledger.corrections(), 'recent': recent, 'undecided': [compact(r) for r in pending]},
            ensure_ascii=False, default=str)
        answer = ask(prompt, config)
        allowed = ids | {r['id'] for r in recent if r['decision']['by'] == 'ai'}
        for item in answer['decisions']:
            if item['id'] not in allowed:
                continue
            ledger.decide(item['id'], item['kind'], item['category'], item['counts'], item['linked'], item['reasoning'],
                          max(0.0, min(1.0, float(item['confidence']))), item['question'].strip(), 'ai')
            decided += item['id'] in ids
        insights = answer['insights']
        if not any(r['id'] in {i['id'] for i in answer['decisions']} for r in pending):
            break  # the model returned nothing for this batch; do not loop forever
    if insights is not None:
        ledger.set_setting('insights', insights)
    return decided, insights
