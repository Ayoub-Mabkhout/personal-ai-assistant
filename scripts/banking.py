"""Money feature: link banks (read-only consent), sync, let the AI auditor decide, publish to the phone.

  banking.py status
  banking.py link deutsche-bank|revolut     opens the bank's consent page, waits for your approval
  banking.py sync [--attended]              fetches transactions (max 4 unattended fetches a day)
  banking.py audit                          AI decisions for new transactions, then insights
  banking.py run                            sync + owner answers/questions + audit + publish
  banking.py watch [--interval 21600]       supervised unattended run loop
  banking.py summary                        totals for the current allowance period
  banking.py allowance AMOUNT [--start-day N] [--definition TEXT]
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import sys
import threading
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from personal_assistant.banking import service  # noqa: E402
from personal_assistant.banking.agent import audit  # noqa: E402
from personal_assistant.banking.ledger import cents, summarise  # noqa: E402
from personal_assistant.relay.client import OwnerClient  # noqa: E402
from personal_assistant.worker.runtime import Singleton  # noqa: E402

CONVERSATIONS = '/relay/v1/banking/conversations'


def collect_questions(relay, ledger):
    """Copy first, then acknowledge; a retry reuses the same durable job key."""
    collected = 0
    while True:
        items = relay.call(CONVERSATIONS + '/pending')['items']
        if not items:
            return collected
        for item in items:
            service.ask_question(ledger, item['id'], item['text'])
            relay.call(CONVERSATIONS + '/' + item['id'] + '/ack', {}, method='POST')
            collected += 1


def publish_replies(relay, ledger):
    delivered = 0
    after = None
    while True:
        path = CONVERSATIONS + '/unanswered' + ('?after=' + after if after else '')
        items = relay.call(path)['items']
        for item in items:
            sequence = service.ask_question(ledger, item['id'], item['text'])
            answer = ledger.audit_output(sequence)
            if answer:
                relay.call(CONVERSATIONS + '/' + item['id'] + '/answer', {'text': answer}, method='PUT')
                delivered += 1
        if len(items) < 100:
            break
        after = items[-1]['id']
    return delivered


def publish_full(relay, ledger):
    summary = summarise(ledger)
    summary['generated'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    relay.call(service.RELAY + '/summary', summary, method='PUT')
    return summary


def run_once(config, ledger, relay):
    with Singleton(ledger.path.with_name('money-delivery.lock')):
        report = {'sync': service.sync(config, ledger) if ledger.accounts() else []}
        delivery_errors = []
        for name, action in (('answers', lambda: service.settle(relay, ledger)),
                             ('questions', lambda: collect_questions(relay, ledger))):
            try: report[name] = action()
            except Exception as error: delivery_errors.append('%s: %s' % (name, type(error).__name__))
        try:
            report['decided'] = audit(ledger, config)[0]
        finally:
            try: report['replies'] = publish_replies(relay, ledger)
            except Exception as error: delivery_errors.append('replies: %s' % type(error).__name__)
            try:
                summary = publish_full(relay, ledger)
                report.update(spent=summary['spent_cents'], remaining=summary['remaining_cents'], review=len(summary['review']))
            except Exception as error: delivery_errors.append('summary: %s' % type(error).__name__)
        if delivery_errors:
            raise RuntimeError('Money relay delivery needs retry (%s).' % ', '.join(delivery_errors))
        return report


def watch(config, ledger, interval):
    if interval < 21600:
        raise ValueError('Unattended Money runs must be at least six hours apart.')
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    while not stop.is_set():
        try:
            report = run_once(config, ledger, OwnerClient(config))
            print(json.dumps({'status': 'ok', 'accounts': len(report['sync']), 'decided': report['decided'],
                              'questions': report['questions'], 'replies': report['replies']}), flush=True)
        except Exception as error:
            print('Money run failed: %s' % type(error).__name__, file=sys.stderr, flush=True)
        stop.wait(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default=str(Path.home() / '.personal-assistant' / 'worker' / 'config.json'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    linking = commands.add_parser('link'); linking.add_argument('bank', choices=sorted(service.BANKS))
    linking.add_argument('--no-browser', action='store_true')
    syncing = commands.add_parser('sync'); syncing.add_argument('--attended', action='store_true')
    commands.add_parser('audit'); commands.add_parser('run'); commands.add_parser('summary')
    watching = commands.add_parser('watch'); watching.add_argument('--interval', type=int, default=21600)
    category = commands.add_parser('category', help='your own category edits; the auditor never overrides them')
    category.add_argument('name'); category.add_argument('--emoji'); category.add_argument('--group')
    category.add_argument('--budget', help='monthly budget in euros'); category.add_argument('--rename')
    category.add_argument('--merge-into'); category.add_argument('--delete', action='store_true')
    commands.add_parser('categories')
    allowance = commands.add_parser('allowance'); allowance.add_argument('amount')
    allowance.add_argument('--start-day', type=int); allowance.add_argument('--definition')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    ledger = service.open_ledger(config)
    out = lambda value: print(json.dumps(value, indent=1, ensure_ascii=False, default=str))
    if args.command == 'status':
        client = service.provider(config)
        app = client.application()
        out({'application': app.get('active'),
             'banks': [{'bank': row['bank'], 'valid_until': row['valid_until']} for row in ledger.banks()],
             'accounts': len(ledger.accounts())})
    elif args.command == 'link':
        relay = OwnerClient(config)
        def show(url):
            print('Approve the read-only access in your bank:', url, flush=True)
            if not args.no_browser: webbrowser.open(url)
        session = service.link(config, args.bank, relay, ledger, show=show)
        publish_full(relay, ledger)
        out({'linked': service.BANKS[args.bank][0], 'accounts': len(session.get('accounts') or []),
             'valid_until': (session.get('access') or {}).get('valid_until')})
    elif args.command == 'sync':
        with Singleton(ledger.path.with_name('money-delivery.lock')):
            out(service.sync(config, ledger, attended=args.attended))
    elif args.command == 'audit':
        relay = OwnerClient(config) if config.get('relay_url') else None
        delivery_error = None
        if relay:
            try: collect_questions(relay, ledger)
            except Exception as error: delivery_error = type(error).__name__
        decided, insights = audit(ledger, config)
        replies = 0
        if relay:
            try: replies = publish_replies(relay, ledger)
            except Exception as error: delivery_error = type(error).__name__
        out({'decided': decided, 'insights': insights, 'replies': replies, 'delivery_error': delivery_error})
    elif args.command == 'run':
        out(run_once(config, ledger, OwnerClient(config)))
    elif args.command == 'watch':
        watch(config, ledger, args.interval)
    elif args.command == 'summary':
        summary = summarise(ledger); summary.pop('transactions')
        out(summary)
    elif args.command == 'categories':
        out(ledger.categories())
    elif args.command == 'category':
        known = any(c['name'] == args.name for c in ledger.categories())
        op = {'op': 'delete' if args.delete else 'merge' if args.merge_into else 'update' if known else 'create',
              'name': args.name, 'emoji': args.emoji, 'group': args.group, 'new_name': args.rename, 'into': args.merge_into,
              'budget_cents': cents(args.budget) if args.budget else None}
        out({'applied': ledger.apply_category_op(op, 'owner')})
    elif args.command == 'allowance':
        value = ledger.setting('allowance')
        value['amount_cents'] = cents(args.amount)
        if args.start_day: value['start_day'] = args.start_day
        if args.definition: value['definition'] = args.definition
        ledger.set_setting('allowance', value); out(value)


if __name__ == '__main__':
    main()
