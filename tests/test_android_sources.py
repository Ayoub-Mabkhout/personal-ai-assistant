"""Compile-free checks of the Android companion sources; the real build only runs on release tags."""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID = Path(__file__).resolve().parents[1] / 'apps/android'
RES, SRC = ANDROID / 'res', ANDROID / 'src'
NS = '{http://schemas.android.com/apk/res/android}'
FILE_RESOURCES = {'anim', 'animator', 'color', 'drawable', 'font', 'interpolator', 'layout', 'menu', 'mipmap', 'raw', 'transition', 'xml'}
ARITY = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'Q': 4, 'A': 7, 'O': 3, 'R': 5, 'Z': 0}


def java_files():
    return sorted(SRC.rglob('*.java'))


def resource_files():
    return sorted(RES.rglob('*.xml')) + [ANDROID / 'AndroidManifest.xml']


def values_names(folder):
    names = set()
    for path in sorted((RES / folder).glob('*.xml')):
        for node in ET.parse(path).getroot():
            kind = node.attrib.get('type') if node.tag == 'item' else node.tag
            if node.attrib.get('name'):
                names.add((kind, node.attrib['name'].replace('.', '_')))
            if node.tag == 'declare-styleable':
                names.update(('attr', attr.attrib['name']) for attr in node)
    return names


def defined_resources():
    defined = set(values_names('values'))
    for folder in RES.iterdir():
        kind = folder.name.split('-')[0]
        if kind in FILE_RESOURCES:
            defined.update((kind, path.stem) for path in folder.iterdir())
        elif kind == 'values':
            defined |= values_names(folder.name)
    for path in resource_files():
        defined.update(('id', name) for name in re.findall(r'@\+id/(\w+)', path.read_text(encoding='utf-8')))
    return defined


def without_comments(source):
    return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', lambda m: m.group(0) if m.group(0)[0] == '"' else ' ', source, flags=re.S)


class AndroidSourceTests(unittest.TestCase):
    def test_every_referenced_resource_is_defined(self):
        defined, missing = defined_resources(), []
        for path in resource_files():
            text = path.read_text(encoding='utf-8')
            for kind, name in re.findall(r'(?<![\w:])@(?!\+|android:)([a-z]+)/([\w.]+)', text):
                if (kind, name.replace('.', '_')) not in defined:
                    missing.append((path.relative_to(ANDROID).as_posix(), kind, name))
            for parent in re.findall(r'parent="([\w.]+)"', text):
                if not parent.startswith('android:') and ('style', parent.replace('.', '_')) not in defined:
                    missing.append((path.relative_to(ANDROID).as_posix(), 'style parent', parent))
        for path in java_files():
            for kind, name in re.findall(r'(?<![\w.])R\.([a-z]+)\.(\w+)', path.read_text(encoding='utf-8')):
                if kind != 'styleable' and (kind, name) not in defined:
                    missing.append((path.relative_to(ANDROID).as_posix(), kind, name))
        self.assertTrue(defined)
        self.assertEqual(sorted(set(missing)), [])

    def test_manifest_components_have_a_class(self):
        manifest = ET.parse(ANDROID / 'AndroidManifest.xml').getroot()
        package = manifest.attrib['package']
        found = 0
        for node in manifest.iter():
            name = node.attrib.get(NS + 'name', '')
            if node.tag in ('activity', 'service', 'receiver', 'provider'):
                found += 1
                qualified = package + name if name.startswith('.') else name
                self.assertTrue((SRC / (qualified.replace('.', '/') + '.java')).exists(), qualified)
        self.assertTrue(found)

    def test_night_resources_only_override_existing_names(self):
        self.assertEqual(sorted(values_names('values-night') - values_names('values')), [])

    def test_glyph_paths_are_well_formed_and_every_used_kind_exists(self):
        ui = (SRC / 'com/personalassistant/companion/AppUi.java').read_text(encoding='utf-8')
        table = re.search(r'DATA=\{(.*?)\};', ui, re.S).group(1)
        entries = re.findall(r'"([^"]*)"', table)
        self.assertEqual(len(entries) % 2, 0)
        kinds = dict(zip(entries[::2], entries[1::2]))
        self.assertEqual(len(kinds), len(entries) // 2, 'duplicate glyph kind')
        for kind, data in kinds.items():
            for segment in data.split('|'):
                body = segment[1:] if segment[:1] in 'FB' else segment
                for command, numbers in re.findall(r'([A-Za-z])([^A-Za-z]*)', body):
                    with self.subTest(kind=kind, segment=segment):
                        self.assertIn(command, ARITY)
                        count = len(re.findall(r'-?\d*\.\d+|-?\d+', numbers))
                        self.assertEqual(count % ARITY[command] if ARITY[command] else count, 0)
                        self.assertTrue(count or command == 'Z')
        used = set()
        for path in java_files():
            text = path.read_text(encoding='utf-8')
            used.update(re.findall(r'\b(?:glyph|iconButton|empty)\("([a-z][a-z-]*)"', text))
            used.update(re.findall(r'Glyphs\.draw\([^,]+,\s*"([a-z][a-z-]*)"', text))
            used.update(re.findall(r'\bicon\(\w+,\s*"([a-z][a-z-]*)"', text))
            used.update(re.findall(r'\bIcon\(\w[\w.]*,\s*"([a-z][a-z-]*)"', text))
            used.update(re.findall(r'\bactionRow\(\s*"[^"]*"\s*,\s*"([a-z][a-z-]*)"', text))
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(kinds)), [], 'an unknown kind silently draws the fallback ring')

    def test_notifications_and_tiles_use_the_app_icons(self):
        icons = []
        for path in java_files():
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('android.R.drawable', text, path.name)
            icons += re.findall(r'setSmallIcon\(([^)]*)\)', text)
        self.assertTrue(icons)
        self.assertEqual(set(icons), {'R.drawable.ic_stat_assistant'})

    def test_sources_stay_at_java_8(self):
        later = {
            r'\bvar\s+\w+\s*=': 'var', r'\b(?:List|Set|Map)\.of\(': 'collection factory', r'\.isBlank\(|\.strip\(\)|\.repeat\(': 'String API after 8',
            r'\bcase\b[^:;\n]*->': 'switch expression', r'\brecord\s+\w+\s*\(': 'record', r'\binstanceof\s+[\w.<>]+\s+\w+\s*[)&|]': 'pattern matching',
        }
        for path in java_files():
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('"""', text, path.name + ': text block')
            code = without_comments(text)
            for pattern, label in later.items():
                self.assertIsNone(re.search(pattern, code), '%s: %s' % (path.name, label))


if __name__ == '__main__':
    unittest.main()
