"""Call the authenticated release hook after publishing the APK and sidecar."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from personal_assistant.worker.notifications import HomeAssistantNotifier


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('metadata',type=Path,help='Published companion.release.json sidecar')
    cli.add_argument('--config',type=Path,default=Path.home()/'.personal-assistant/worker/config.json')
    args=cli.parse_args()
    metadata=json.loads(args.metadata.read_text(encoding='utf-8'))
    config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    response=HomeAssistantNotifier(config).call('/groceries/v1/mobile/release/published',
        {'version_code':metadata['version_code'],'sha256':metadata['sha256']})
    print(json.dumps(response))


if __name__=='__main__':
    main()
