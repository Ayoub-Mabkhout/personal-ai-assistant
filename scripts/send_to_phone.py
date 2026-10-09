"""Send one file the owner asked for to the paired Companion phone's Downloads.

Uses the protected worker config (relay_url plus worker or submit token file); no
credential is passed on the command line. Prints the relay's JSON record.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from personal_assistant.worker.runtime import TransportError
from personal_assistant.worker.send_file import client_from_config, send_from_config


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('path', type=Path, nargs='?', help='File to send.')
    cli.add_argument('--name', help='File name shown on the phone (default: the file name).')
    cli.add_argument('--note', default='', help='Short note shown in the phone notification (max 300 characters).')
    cli.add_argument('--mime', help='MIME type (default: guessed from the name).')
    cli.add_argument('--phone', help='Phone ID; omitted only when exactly one phone is paired.')
    cli.add_argument('--id', help='Stable transfer ID; reuse it when retrying. Default: derived from name, content and note.')
    cli.add_argument('--status', metavar='ID', help='Report the saved state of an earlier transfer instead of sending.')
    cli.add_argument('--list-phones', action='store_true', help='List paired phones and the size limit.')
    cli.add_argument('--config', type=Path, default=Path.home() / '.personal-assistant/worker/config.json',
                     help='Protected worker config.')
    return cli


def main():
    cli = parser()
    args = cli.parse_args()
    if not (args.path or args.status or args.list_phones):
        cli.error('Give a file path, --status ID or --list-phones.')
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        if args.list_phones:
            result = client_from_config(config).call('/v1/files/phones')
        elif args.status:
            result = client_from_config(config).call('/v1/files/' + args.status)
        else:
            result = send_from_config(config, args.path, name=args.name, note=args.note, mime=args.mime,
                                      phone=args.phone, request_id=args.id)
    except TransportError as error:
        print(json.dumps({'error': str(error), 'status': error.status}, ensure_ascii=False), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
