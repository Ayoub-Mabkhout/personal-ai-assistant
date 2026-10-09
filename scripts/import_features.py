"""Import an initial features checklist into the relay store; safe to run again.

The input is a private JSON list kept under ignored state/, for example
state/features.json: [{"title": "...", "detail": "...", "area": "companion", "done": false}].
An entry without "id" gets one derived from its area and title, so a repeated
import never adds a second copy. Entries already on the relay keep any edits or
checks made since, and an entry deleted on the relay is not brought back.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from personal_assistant.relay.features import FeatureEdit, NewFeature


def entries(raw):
    if not isinstance(raw, list):
        raise ValueError('The features file must contain a JSON list.')
    result = []
    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            raise ValueError(f'Entry {index+1} must be an object.')
        value = dict(value)
        done = value.pop('done', False)
        if not isinstance(done, bool):
            raise ValueError(f'Entry {index+1}: "done" must be true or false.')
        if 'id' not in value and isinstance(value.get('title'), str):
            key = (value.get('area', 'assistant')+'\n'+' '.join(value['title'].split()).casefold()).encode()
            value['id'] = 'import-'+hashlib.sha256(key).hexdigest()[:32]
        try:
            feature = NewFeature.model_validate(value)
        except ValueError as error:
            raise ValueError(f'Entry {index+1} is invalid: {error}') from None
        result.append((feature, done))
    return result


def run(client, raw, base='/v1/features'):
    from personal_assistant.worker.runtime import TransportError
    summary = {'added': 0, 'already_present': 0, 'previously_deleted': 0}
    planned = entries(raw)
    existing = {item['id'] for item in client.call(base)['items']}
    for feature, done in planned:
        if feature.id in existing:
            # Never overwrite an entry that may have been edited or checked since.
            summary['already_present'] += 1
            continue
        try:
            item = client.call(base, feature.model_dump(exclude_none=True))
        except TransportError as error:
            if error.status != 409:
                raise
            summary['previously_deleted'] += 1
            continue
        if done and not item['done']:
            client.call(base+'/'+item['id'], FeatureEdit(done=True).model_dump(exclude_none=True), 'PATCH')
        existing.add(item['id'])
        summary['added'] += 1
    return summary


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument('--file', type=Path, default=ROOT/'state/features.json')
    cli.add_argument('--config', type=Path, default=Path.home()/'.personal-assistant/worker/config.json',
                     help='Protected worker config with relay_url and submit_token_file.')
    args = cli.parse_args()
    from personal_assistant.worker.runtime import RelayClient
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    client = RelayClient(config['relay_url'], config['submit_token_file'])
    print(json.dumps(run(client, json.loads(args.file.read_text(encoding='utf-8-sig'))), indent=2))


if __name__ == '__main__':
    main()
