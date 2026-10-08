import argparse
import json
from pathlib import Path
from personal_assistant.orchestrator.submit import submit

parser=argparse.ArgumentParser(description='Queue a prompt for the persistent Luna orchestrator.')
parser.add_argument('--prompt-file',type=Path,required=True)
parser.add_argument('--workspace',type=Path)
parser.add_argument('--id')
parser.add_argument('--config',type=Path)
parser.add_argument('--wait',action='store_true')
args=parser.parse_args()
print(json.dumps(submit(args.prompt_file.read_text(encoding='utf-8'),workspace=args.workspace,
    request_id=args.id,config_path=args.config,wait=args.wait),ensure_ascii=False,indent=2))
