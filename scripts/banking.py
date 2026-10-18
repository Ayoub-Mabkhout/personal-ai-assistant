"""Money feature: link banks (read-only consent), sync, let the AI auditor decide, publish to the phone.

  banking.py status
  banking.py link deutsche-bank|revolut     opens the bank's consent page, waits for your approval
  banking.py sync [--attended]              fetches transactions (max 4 unattended fetches a day)
  banking.py audit                          AI decisions for new transactions, then insights
  banking.py run                            sync + phone answers + audit + publish (the scheduled job)
  banking.py summary                        totals for the current allowance period
  banking.py allowance AMOUNT [--start-day N] [--definition TEXT]
"""
import argparse
import json
from pathlib import Path
import sys
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from personal_assistant.banking import service  # noqa: E402
from personal_assistant.banking.agent import audit  # noqa: E402
from personal_assistant.banking.ledger import cents, summarise  # noqa: E402
from personal_assistant.relay.client import OwnerClient  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default=str(Path.home() / '.personal-assistant' / 'worker' / 'config.json'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    linking = commands.add_parser('link'); linking.add_argument('bank', choices=sorted(service.BANKS))
    linking.add_argument('--no-browser', action='store_true')
    syncing = commands.add_parser('sync'); syncing.add_argument('--attended', action='store_true')
    commands.add_parser('audit'); commands.add_parser('run'); commands.add_parser('summary')
    allowance = commands.add_parser('allowance'); allowance.add_argument('amount')
    allowance.add_argument('--start-day', type=int); allowance.add_argument('--definition')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    ledger = service.open_ledger(config)
    out = lambda value: print(json.dumps(value, indent=1, ensure_ascii=False, default=str))
    if args.command == 'status':
        client = service.provider(config)
        app = client.application()
        out({'application': app.get('active'), 'banks': ledger.banks(), 'accounts': len(ledger.accounts())})
    elif args.command == 'link':
        def show(url):
            print('Approve the read-only access in your bank:', url, flush=True)
            if not args.no_browser: webbrowser.open(url)
        session = service.link(config, args.bank, OwnerClient(config), ledger, show=show)
        out({'linked': service.BANKS[args.bank][0], 'accounts': len(session.get('accounts') or []),
             'valid_until': (session.get('access') or {}).get('valid_until')})
    elif args.command == 'sync':
        out(service.sync(config, ledger, attended=args.attended))
    elif args.command == 'audit':
        decided, insights = audit(ledger, config)
        out({'decided': decided, 'insights': insights})
    elif args.command == 'run':
        relay = OwnerClient(config)
        report = {'sync': service.sync(config, ledger), 'answers': service.settle(relay, ledger)}
        report['decided'] = audit(ledger, config)[0]
        summary = service.publish(relay, ledger)
        report.update(spent=summary['spent_cents'], remaining=summary['remaining_cents'], review=len(summary['review']))
        out(report)
    elif args.command == 'summary':
        summary = summarise(ledger); summary.pop('transactions')
        out(summary)
    elif args.command == 'allowance':
        value = ledger.setting('allowance')
        value['amount_cents'] = cents(args.amount)
        if args.start_day: value['start_day'] = args.start_day
        if args.definition: value['definition'] = args.definition
        ledger.set_setting('allowance', value); out(value)


if __name__ == '__main__':
    main()
