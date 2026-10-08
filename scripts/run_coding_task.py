import argparse
import json
from pathlib import Path
from personal_assistant.lab import run_coding_task

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='Run an explicitly requested Codex task with captured execution history.')
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--prompt-file',type=Path,required=True)
    parser.add_argument('--codex',type=Path,help='Legacy argument; the supervised orchestrator uses its configured CLI.')
    parser.add_argument('--node',type=Path)
    args=parser.parse_args()
    print(json.dumps(run_coding_task(args.workspace,args.prompt_file.read_text(encoding='utf-8'),
        args.codex,args.node),indent=2))
