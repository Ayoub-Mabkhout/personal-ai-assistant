"""Attach a requested deliverable to a task answer; retain it in phone task history."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from personal_assistant.worker.task_files import attach
from personal_assistant.worker.runtime import TransportError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path',type=Path)
    parser.add_argument('--task',required=True,help='Current queue job ID, including the current follow-up ID.')
    parser.add_argument('--name',help='Optional display file name.')
    parser.add_argument('--config',type=Path,default=Path.home()/'.personal-assistant/worker/config.json')
    args=parser.parse_args()
    try:
        config=json.loads(args.config.read_text(encoding='utf-8-sig'))
        result=attach(config,args.task,args.path,name=args.name)
    except (OSError,ValueError,RuntimeError,TransportError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False),file=sys.stderr);return 1
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
