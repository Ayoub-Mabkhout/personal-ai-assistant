"""Package deployable source with an allowlist; exclude personal data and keys."""

import argparse
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    'pyproject.toml', 'requirements-server.lock', '.dockerignore',
    'infra/server/compose.yaml', 'infra/server/Dockerfile',
    'infra/server/Caddyfile', 'infra/server/Caddyfile.bootstrap',
    'infra/server/.env.example', 'infra/server/images.lock.json',
    'infra/server/cloud-init.yaml',
    'integrations/home_assistant/configuration.yaml',
    'integrations/home_assistant/task_replies.package.yaml',
    'integrations/home_assistant/custom_sentences/en/assistant.yaml',
    'scripts/prepare_server.py', 'scripts/deploy_server.sh',
    'scripts/onboard_homeassistant.py',
    'scripts/configure_homeassistant_http.py',
    'scripts/configure_homeassistant_voice.py',
    'scripts/configure_homeassistant_dispatch.py', 'scripts/assist_pipeline_config.py',
    'scripts/confirm_homeassistant_https.py',
    'scripts/smoke_server.py', 'docs/server-deployment.md',
)


def build(output, root=ROOT):
    output = Path(output).resolve()
    root = Path(root).resolve()
    paths = [root / name for name in FILES]
    paths.extend((root / 'src/personal_assistant').rglob('*.py'))
    paths.extend((root / 'apps/groceries').glob('*'))
    paths.extend((root / 'apps/tasks').glob('*'))
    paths.extend((root / 'integrations/home_assistant/custom_components').rglob('*.py'))
    paths.extend((root / 'integrations/home_assistant/custom_components').rglob('manifest.json'))
    for path in paths:
        if not path.is_file() or path.resolve() != path.absolute():
            raise ValueError('Missing or symlinked deployment source: ' + str(path))
        if path.resolve() == output:
            raise ValueError('The output cannot replace a source file.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for path in sorted(paths):
            archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    return {'bundle': str(output), 'source_files': len(paths), 'private_directories_included': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'state/exports/server-deployment.tar.gz')
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
