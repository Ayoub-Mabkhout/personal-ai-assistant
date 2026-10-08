import argparse
import json
from personal_assistant.lab import create

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='Prepare a self-contained task workspace.')
    parser.add_argument('name')
    parser.add_argument('--javascript',action='store_true')
    args=parser.parse_args()
    print(json.dumps(create(args.name,javascript=args.javascript),indent=2))
