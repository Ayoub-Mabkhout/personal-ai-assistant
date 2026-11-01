"""Headless workout import/export and specialist status using protected owner credentials."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request
from personal_assistant.relay.client import OwnerClient


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path.home()/'.personal-assistant/worker/config.json')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('import-strong','import-bodyweight'):
        p=commands.add_parser(name);p.add_argument('file',type=Path)
        p.add_argument('--timezone',default='UTC');p.add_argument('--commit',action='store_true')
    commands.add_parser('status')
    p=commands.add_parser('export');p.add_argument('output',type=Path)
    args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    client=OwnerClient(config)
    if args.command.startswith('import-'):
        raw=args.file.read_bytes()
        if len(raw)>32*1024*1024: raise ValueError('Source exceeds 32 MiB')
        query=urlencode({'commit':'true' if args.commit else 'false','timezone':args.timezone})
        token=client.token_file.read_text(encoding='utf-8-sig').strip()
        request=Request(client.origin+'/relay/v1/workout/imports/'+args.command[7:]+'?'+query,data=raw,
                        headers={'Authorization':'Bearer '+token,'Content-Type':'text/csv'},method='POST')
        with client.opener.open(request,timeout=120) as response: result=json.load(response)
    elif args.command=='export':
        result=client.call('/relay/v1/workout/export')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        result={'written':str(args.output),'entities':len(result['entities'])}
    else:
        data=client.call('/relay/v1/workout/overview')
        result={k:data[k] for k in ('completed_workouts','exercise_count','rank_coverage','trainer')}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
