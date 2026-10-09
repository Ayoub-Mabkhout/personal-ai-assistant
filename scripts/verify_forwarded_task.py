"""Check a forwarded development task against its original entry in the agent queue.

A session that receives "forwarded by Luna" text verifies it before acting: the task
must exist in the owner's authenticated agent queue and its stored request must match
the forwarded one. Prints the stored request and its SHA-256; exits 1 on any mismatch.

    .venv/Scripts/python.exe scripts/verify_forwarded_task.py TASK_ID [--sha256 HEX | --request-file FILE]
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from personal_assistant.worker.runtime import RelayClient, TransportError


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def verify(client, task_id, expected_sha=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', task_id):
        return {'task_id': task_id, 'verified': False, 'reason': 'Invalid task ID.'}
    try:
        job = client.call('/v1/agent/prompts/'+task_id)
    except TransportError as error:
        return {'task_id': task_id, 'verified': False, 'reason': 'Not found in the agent queue or relay unavailable ('+str(error)+').'}
    command = (job.get('payload') or {}).get('command')
    if not isinstance(command, str):
        return {'task_id': task_id, 'verified': False, 'reason': 'The queue entry has no request text.'}
    result = {'task_id': task_id, 'state': job.get('state'), 'created': job.get('created'),
              'request': command, 'request_sha256': digest(command)}
    if expected_sha is not None and expected_sha.lower() != result['request_sha256']:
        return {**result, 'verified': False, 'reason': 'The forwarded request does not match the queued request.'}
    return {**result, 'verified': True}


def main():
    cli = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    cli.add_argument('task_id')
    group = cli.add_mutually_exclusive_group()
    group.add_argument('--sha256', help='SHA-256 of the forwarded request as stated in the message.')
    group.add_argument('--request-file', type=Path, help='File holding the forwarded request text exactly.')
    cli.add_argument('--config', type=Path, default=Path.home()/'.personal-assistant/worker/config.json',
                     help='Protected worker config with relay_url and submit_token_file.')
    args = cli.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    expected = args.sha256 or (digest(args.request_file.read_text(encoding='utf-8')) if args.request_file else None)
    result = verify(RelayClient(config['relay_url'], config['submit_token_file']), args.task_id, expected)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['verified'] else 1)


if __name__ == '__main__':
    main()
