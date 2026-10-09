import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.build_deployment_bundle import FILES, build


class DeploymentBundleTests(unittest.TestCase):
    def test_bundle_excludes_private_material_and_local_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'source'
            for name in FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('public source')
            module = root / 'src/personal_assistant/main.py'
            module.parent.mkdir(parents=True)
            module.write_text('print("public code")')
            shared = root / 'apps/shared/daylight.js'
            shared.parent.mkdir(parents=True)
            shared.write_text('/* generic solar calculator */')
            for name in ('private/profile/PROFILE.md', 'config/local/.env',
                         'infra/server/.env', 'state/queue/private.sqlite3',
                         'src/personal_assistant/__pycache__/private.pyc'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('PRIVATE_SENTINEL_NOT_FOR_DEPLOYMENT')
            output = Path(temporary) / 'bundle.tar.gz'
            build(output, root)
            with tarfile.open(output) as archive:
                names = archive.getnames()
                self.assertIn('src/personal_assistant/main.py', names)
                self.assertIn('apps/shared/daylight.js', names)
                for member in archive:
                    self.assertNotIn(b'PRIVATE_SENTINEL_NOT_FOR_DEPLOYMENT', archive.extractfile(member).read())
                    self.assertFalse(member.name.startswith(('private/', 'state/', 'config/local/')))
                    self.assertNotEqual(Path(member.name).name, '.env')


if __name__ == '__main__':
    unittest.main()
