"""Check archived document bytes without contacting any mailbox."""
import argparse
import json
from pathlib import Path
from personal_assistant.connectors.mail import Archive

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    args=parser.parse_args()
    if not (args.archive/'catalog.sqlite3').is_file():
        parser.error('No existing archive catalog at this path.')
    result=Archive(args.archive).verify()
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['ok'] else 1)
