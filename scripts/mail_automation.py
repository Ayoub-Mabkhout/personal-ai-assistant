"""Run bounded live Gmail maintenance through the existing agent queue."""
import argparse
import json
from pathlib import Path
from personal_assistant.mail_automation import MailAutomation, ingest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--loop',action='store_true')
    parser.add_argument('--poll',type=int,default=60)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--repair-job',help='Reimport an already completed maintenance task; no model rerun or coverage advancement.')
    parser.add_argument('--compact-pending',action='store_true',help='Repair an unsubmitted oversized local envelope; never submits or reruns it.')
    parser.add_argument('--trace',type=Path,action='append',default=[])
    args=parser.parse_args()
    automation=MailAutomation(args.config)
    if args.compact_pending:
        print(json.dumps(automation.compact_pending(),ensure_ascii=False,indent=2))
    elif args.repair_job:
        print(json.dumps(automation.repair(args.repair_job),ensure_ascii=False,indent=2))
    elif args.manifest:
        result=ingest(automation.config,json.loads(args.manifest.read_text(encoding='utf-8-sig')),args.trace)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.loop: automation.loop(args.poll)
    else: print(json.dumps(automation.tick(),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
