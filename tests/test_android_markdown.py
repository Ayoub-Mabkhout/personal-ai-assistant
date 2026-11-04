"""Markdown.java, the framework-free reader behind RichText's chat answers, compiled with javac and driven through tests/jvm/MarkdownProbe.java.

The probe prints one line per block; styled runs appear as {b,i,c:text} and links as {=url:text}. Skipped where no JDK is installed."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / 'apps/android/src/com/personalassistant/companion/Markdown.java', ROOT / 'tests/jvm/MarkdownProbe.java']
JAVAC, JAVA = shutil.which('javac'), shutil.which('java')
BUILD = None


def setUpModule():
    global BUILD
    if not (JAVAC and JAVA):
        return
    BUILD = tempfile.TemporaryDirectory(prefix='assistant-markdown-')
    for flags in (['--release', '8'], []):
        built = subprocess.run([JAVAC, '-encoding', 'UTF-8', *flags, '-d', BUILD.name, *map(str, SOURCES)], capture_output=True, text=True)
        if built.returncode == 0:
            return
    raise RuntimeError(built.stderr)


def tearDownModule():
    if BUILD:
        BUILD.cleanup()


def parse(*docs):
    run = subprocess.run([JAVA, '-Dfile.encoding=UTF-8', '-cp', BUILD.name, 'com.personalassistant.companion.MarkdownProbe'],
                         input='\u001e'.join(docs).encode('utf-8'), capture_output=True, check=True)
    return [part.strip('\r\n').splitlines() for part in run.stdout.decode('utf-8').split('\u001e')[:len(docs)]]


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile Markdown.java')
class MarkdownTests(unittest.TestCase):
    def test_inline_styles_and_literal_fallbacks(self):
        [lines] = parse('**bold**, *it*, _it_, ***both***, `a*b*`, snake_case_name, 2 * 3 * 4, \\*not\\*, ``a`b``')
        self.assertEqual(lines, ['P {b:bold}, {i:it}, {i:it}, {bi:both}, {c:a*b*}, snake_case_name, 2 * 3 * 4, *not*, {c:a`b}'])

    def test_streaming_prefixes_stay_literal_or_open(self):
        unclosed, fence, link = parse('**half *way `co', '```py\nx = **1**\n\ny', 'see [docs](https://ex')
        self.assertEqual(unclosed, ['P **half *way `co'])
        self.assertEqual(fence, ['CODE(py) open x = **1**\\n\\ny'])
        self.assertEqual(link[0][:10], 'P see [doc')
        document = '# Plan\n\n- **one** with `code`\n  - nested [x](https://ex.com)\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```\nend\n```\n'
        parse(*[document[:n] for n in range(len(document) + 1)])

    def test_blocks(self):
        [lines] = parse('# Title ##\n### Small\npara\nline two\n- a\n- b\n  wrapped\n  - nested\n1. one\n2) two\n\n  more of two\n---\n> quote **x**\n> - item\n```\ncode\n```')
        self.assertEqual(lines, ['H1 Title', 'H3 Small', 'P para\\nline two', 'LI0(-) a', 'LI0(-) b wrapped', 'LI1(-) nested', 'LI0(1.) one', 'LI0(2)) two',
                                 'LI0 more of two', 'HR', 'QUOTE', '  P quote {b:x}', '  LI0(-) item', 'CODE code'])

    def test_links_only_for_web_and_mail(self):
        [lines] = parse('[a](https://ex.com/a_(b)) [b](javascript:alert(1)) <mailto:me@example.com> see https://ex.com/p). x_https://no')
        self.assertEqual(lines, ['P {=https://ex.com/a_(b):a} b {=mailto:me@example.com:me@example.com} see {=https://ex.com/p:https://ex.com/p}). x_https://no'])

    def test_tables(self):
        [lines] = parse('| Name | Note |\n|:--|--:|\n| `a|b` | x \\| y |\n| **1** |\nafter')
        self.assertEqual(lines, ['TABLE | Name | Note | | {c:a|b} | x | y | | {b:1} |', 'P after'])


if __name__ == '__main__':
    unittest.main()
