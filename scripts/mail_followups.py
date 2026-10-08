"""Inspect and manage source-qualified mail deadlines and pending replies."""
import argparse
import json
from pathlib import Path
from personal_assistant.mail_followups import Followups


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    listing=commands.add_parser('list')
    listing.add_argument('--state',choices=['open','resolved','dismissed','all'],default='open')
    listing.add_argument('--before')
    for action in ('resolve','dismiss','reopen'):
        child=commands.add_parser(action);child.add_argument('id');child.add_argument('--note',default='')
    args=parser.parse_args();config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    store=Followups(config['followups_db'],config['archive'],config.get('policy'))
    if args.command=='list': result=store.list(None if args.state=='all' else args.state,args.before)
    else: result=store.set_state(args.id,{'resolve':'resolved','dismiss':'dismissed','reopen':'open'}[args.command],args.note)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
