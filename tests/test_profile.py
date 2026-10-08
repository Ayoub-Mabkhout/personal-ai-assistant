import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from scripts.prepare_profile import import_chatgpt_profile


class ProfileTests(unittest.TestCase):
    def test_import_keeps_original_and_excludes_third_party_theme(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            profile=root/'profile'
            profile.mkdir()
            (profile/'PROFILE.md').write_text('# Prior profile\n')
            source=root/'export.md'
            parts=['# Supplied profile\n']
            for number in range(1,28):
                body='Explicit excluded third-party memory' if number==26 else f'Theme content {number}'
                parts.append(f'## {number}. Topic\n\n{body}\n')
            original='\r\n'.join(parts).encode()
            source.write_bytes(original)
            import_chatgpt_profile(source,profile)
            manifest=json.loads((profile/'manifest.json').read_text())
            self.assertEqual(manifest['source_sha256'],hashlib.sha256(original).hexdigest())
            self.assertEqual((profile/manifest['source']).read_bytes(),original)
            for theme in manifest['themes']:
                self.assertNotIn('Explicit excluded third-party memory',(profile/theme['file']).read_text())
            (profile/'identity.md').write_text('A later direct correction\n')
            import_chatgpt_profile(source,profile)
            saved=list((profile/'sources/theme-history').glob('identity-*.md'))
            self.assertTrue(any(path.read_text()=='A later direct correction\n' for path in saved))


if __name__=='__main__':
    unittest.main()
