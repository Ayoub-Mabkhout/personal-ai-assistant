"""Static contracts that tie each web page's markup, script, service worker, CSP and server whitelist together."""
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from personal_assistant.relay.api import create_app
from personal_assistant.relay.store import Queue
from personal_assistant.relay.tasks import task_router

APPS = Path(__file__).resolve().parents[1] / 'apps'


class Page(HTMLParser):
    """Collects what the strict CSP and the page script depend on."""

    def __init__(self):
        super().__init__()
        self.ids, self.symbols, self.uses, self.refs, self.dynamic_ids, self.violations = set(), set(), set(), set(), set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id'):
            self.ids.add(a['id'])
        if tag == 'symbol':
            self.symbols.add(a.get('id'))
        if tag == 'use' and a.get('href', '').startswith('#'):
            self.uses.add(a['href'][1:])
        if tag in ('script', 'link', 'img') and (a.get('src') or a.get('href')):
            self.refs.add(a.get('src') or a.get('href'))
        for name in ('data-tab', 'data-copy'):
            if name in a:
                self.dynamic_ids.add(a[name])
        if tag == 'style':
            self.violations.append('<style> block')
        if 'style' in a:
            self.violations.append('style attribute on <%s>' % tag)
        self.violations.extend('%s handler on <%s>' % (name, tag) for name in a if name.startswith('on'))
        if tag == 'script' and not a.get('src'):
            self.violations.append('inline <script>')


def page(app):
    parser = Page()
    parser.feed((APPS / app / 'index.html').read_text(encoding='utf-8'))
    return parser


class WebPageContracts(unittest.TestCase):
    def test_pages_use_no_inline_code_and_script_lookups_resolve(self):
        for app in ('groceries', 'tasks'):
            html, js = page(app), (APPS / app / 'app.js').read_text(encoding='utf-8')
            with self.subTest(app):
                self.assertEqual(html.violations, [], 'the CSP blocks inline code and styles')
                looked_up = set(re.findall(r"\$\('([^']+)'\)", js))
                self.assertEqual(sorted(looked_up - html.ids), [], 'app.js looks up ids that index.html does not define')
                self.assertEqual(sorted(html.dynamic_ids - html.ids), [], 'data-tab/data-copy must name an element id')
                self.assertEqual(sorted(html.uses - html.symbols), [])
                literal = set(re.findall(r"['\"]#?(i-[a-z0-9-]+)['\"]", js)) | {'i-' + n for n in re.findall(r"\bicon\('(?!i-)([a-z0-9-]+)'\)", js)}
                self.assertEqual(sorted(literal - html.symbols), [], 'icon without a <symbol>')
                self.assertEqual(re.findall(r"setAttribute\(\s*'style'|insertAdjacentHTML|\.innerHTML\s*=", js), [])

    def test_groceries_shell_is_precached_served_and_versioned_once(self):
        root = APPS / 'groceries'
        sw = (root / 'sw.js').read_text(encoding='utf-8')
        precache = set(re.findall(r"'/groceries/([^']*)'", re.search(r'ASSETS=\[(.*?)\]', sw).group(1)))
        shell = {re.sub(r'\?.*', '', ref).removeprefix('/groceries/') for ref in page('groceries').refs}
        self.assertLessEqual(shell, precache, 'the offline shell would miss a file the page loads')
        with tempfile.TemporaryDirectory() as raw, TestClient(create_app(Path(raw) / 'q.sqlite3', 's' * 48, 'w' * 48, groceries={
                'path': Path(raw) / 'g.sqlite3', 'internal_token': 'g' * 48, 'ha_url': 'http://unused', 'assets': root,
                'user_verifier': lambda token: None})) as client:
            for name in sorted(precache | {'sw.js'}):
                self.assertEqual(client.get('/groceries/' + name).status_code, 200, name)
        versions = set(re.findall(r'\?v=([0-9A-Za-z-]+)', (root / 'index.html').read_text(encoding='utf-8')))
        self.assertEqual(len(versions), 1, 'one cache-busting token for style, theme and script')

    def test_tasks_shell_is_served_by_the_task_router(self):
        with tempfile.TemporaryDirectory() as raw:
            queue = Queue(Path(raw) / 'agent.sqlite3')
            app = FastAPI()
            app.include_router(task_router({'agent': queue, 'command': queue}, 'https://ha.example.com', APPS / 'tasks'))
            with TestClient(app) as client:
                refs = sorted(ref for ref in page('tasks').refs if ref.startswith('/tasks/'))
                self.assertTrue(refs)
                for ref in refs:
                    self.assertEqual(client.get(ref).status_code, 200, ref)


if __name__ == '__main__':
    unittest.main()
