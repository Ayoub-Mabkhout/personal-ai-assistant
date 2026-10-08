"""Create the private workspace folders and templates without replacing files."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    layout = json.loads((ROOT / 'config/workspace-layout.json').read_text(encoding='utf-8'))
    local_layout = ROOT / 'config/local/workspace-layout.json'
    if local_layout.exists():
        additions = json.loads(local_layout.read_text(encoding='utf-8'))
        for key in ('private_directories', 'state_directories'):
            layout[key].extend(additions.get(key, []))
    created = []
    for base, key in ((ROOT / 'private', 'private_directories'), (ROOT / 'state', 'state_directories')):
        for relative in layout[key]:
            target = (base / relative).resolve()
            if not target.is_relative_to(base.resolve()):
                raise ValueError('Workspace layout must stay inside its private directory.')
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                created.append(target.relative_to(ROOT).as_posix())
    (ROOT / 'config/local').mkdir(parents=True, exist_ok=True)
    for source, target in (
        ('config/templates/profile.md', 'private/profile/PROFILE.md'),
        ('config/templates/preferences.md', 'private/profile/PREFERENCES.md'),
        ('config/templates/accounts.json', 'private/auth/accounts.json'),
    ):
        destination = ROOT / target
        if not destination.exists():
            destination.write_text((ROOT / source).read_text(encoding='utf-8'), encoding='utf-8')
            created.append(target)
    print(json.dumps({'created': created, 'existing_files_preserved': True}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
