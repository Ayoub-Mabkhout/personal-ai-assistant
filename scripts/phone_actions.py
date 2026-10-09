"""Queue phone alarms using protected relay owner credentials."""
import argparse
import json
from pathlib import Path
import re
import sys
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from personal_assistant.relay.client import OwnerClient


BASE = '/groceries/v1/mobile/'


def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', value):
        raise argparse.ArgumentTypeError('Use a stable ID of 8–64 letters, numbers, underscores or hyphens.')
    return value


def clock_time(value):
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
        raise argparse.ArgumentTypeError('Use a 24-hour HH:MM time, for example 07:30.')
    return tuple(int(part) for part in value.split(':'))


def select_phone(phones, requested=None):
    active = [phone for phone in phones if not phone.get('revoked')]
    if requested:
        if not any(phone['id'] == requested for phone in active):
            raise ValueError('That phone is not paired or has been revoked. List paired phones first.')
        return requested
    if len(active) == 1:
        return active[0]['id']
    if not active:
        raise ValueError('Install and pair Assistant Companion first; no active phone is paired.')
    raise ValueError('More than one phone is paired. Ask which phone to use and pass its ID with --phone.')


def execute(args, client):
    if args.action == 'phones':
        return {'phones':client.call(BASE+'phones')}
    if args.action == 'status':
        return client.call(BASE+'alarms/'+args.id)
    if args.action == 'termux-status':
        return client.call(BASE+'termux/commands/'+args.id)
    if args.action == 'termux-capabilities':
        return client.call(BASE+'termux/capabilities')
    phone = select_phone(client.call(BASE+'phones'), args.phone)
    if args.action == 'termux':
        script=args.script_file.read_text(encoding='utf-8') if args.script_file else args.script
        return client.call(BASE+'termux/commands',{'id':args.id,'phone':phone,'script':script,
                                                'workdir':args.workdir,'label':args.label,'timeout':args.timeout,'ttl':args.ttl})
    hour, minute = args.time
    return client.call(BASE+'alarms', {'id':args.id, 'phone':phone, 'hour':hour, 'minute':minute,
                                     'label':args.label, 'launch':args.launch})


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--config', type=Path, default=Path.home()/'.personal-assistant/worker/config.json',
                     help='Protected config containing relay_url and submit_token_file.')
    commands = cli.add_subparsers(dest='action', required=True)
    commands.add_parser('phones', help='List paired phones; this does not send a phone command.')
    alarm = commands.add_parser('alarm', help='Queue an alarm; phone Clock creation must be checked separately.')
    alarm.add_argument('--id', type=identifier, required=True, help='Stable request ID; reuse on retries.')
    alarm.add_argument('--time', type=clock_time, required=True, metavar='HH:MM', help='Time in the phone Clock local timezone.')
    alarm.add_argument('--label', default='Alarm', help='Clock label (maximum 200 characters).')
    alarm.add_argument('--phone', type=identifier, help='Phone ID; omitted only when exactly one active phone is paired.')
    alarm.add_argument('--launch', action='store_true',
                       help='Native Companion shows a tap-to-set-alarm card; intent registration requires handset verification.')
    status = commands.add_parser('status', help='Read the saved alarm delivery state.')
    status.add_argument('id', type=identifier)
    termux=commands.add_parser('termux',help='Queue a phone script; Termux installation and command permission required.')
    termux.add_argument('--id',type=identifier,required=True)
    source=termux.add_mutually_exclusive_group(required=True)
    source.add_argument('--script');source.add_argument('--script-file',type=Path)
    termux.add_argument('--phone',type=identifier)
    termux.add_argument('--workdir',default='~/')
    termux.add_argument('--label',default='Phone command')
    termux.add_argument('--timeout',type=int,default=60)
    termux.add_argument('--ttl',type=int,default=3600)
    commands.add_parser('termux-capabilities',help='Check installation, permission and bridge enablement reported by paired phones.')
    termux_status=commands.add_parser('termux-status',help='Read saved stdout, stderr, exit code and command state.')
    termux_status.add_argument('id',type=identifier)
    return cli


def main():
    cli = parser()
    args = cli.parse_args()
    if args.action == 'alarm' and len(args.label) > 200:
        cli.error('Alarm label must contain at most 200 characters.')
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        result = execute(args, OwnerClient(config))
    except urllib.error.HTTPError as error:
        print(json.dumps({'error':'Server rejected the phone request.', 'status':error.code}), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'error':str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
