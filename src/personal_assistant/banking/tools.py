"""Lease-scoped Money MCP tools. Private ledger and downloaded marks stay local."""
import argparse
import base64
import json
from pathlib import Path
import re
import struct
import sys
import urllib.parse
import urllib.request

from .ledger import Ledger, annotation_public


def logo_catalog(ledger):
    with ledger.db() as db:
        return {r['merchant_name']: r['data_uri'] for r in db.execute('SELECT merchant_name,data_uri FROM merchant_logos')}


class MoneyTools:
    def __init__(self, ledger, token, fetch=None):
        self.ledger, self.token, self.fetch = ledger, token, fetch or self.download

    def fenced(self, db):
        state = db.execute('SELECT lease_token,lease_until FROM audit_state WHERE id=1').fetchone()
        if not state or state['lease_token'] != self.token or (state['lease_until'] or 0) <= self.ledger.clock():
            raise ValueError('The Money session lease is no longer active')

    @staticmethod
    def download(url):
        request = urllib.request.Request(url, headers={'User-Agent': 'PersonalAssistant/1.0'})
        with urllib.request.urlopen(request, timeout=12) as response:
            location=urllib.parse.urlparse(response.geturl())
            if location.scheme!='https' or location.hostname not in ('www.google.com', 't0.gstatic.com', 't1.gstatic.com', 't2.gstatic.com', 't3.gstatic.com'):
                raise ValueError('Unexpected logo redirect')
            return response.read(32769)

    def call(self, name, args):
        with self.ledger.db() as db:
            self.fenced(db)
        if name == 'transactions_search':
            rows = self.ledger.transactions()
            query = str(args.get('query', '')).casefold()
            rows = [r for r in rows if (not args.get('missing_only') or not r.get('annotation_by'))
                    and query in (' '.join(str(r.get(k) or '') for k in ('counterparty', 'description', 'display_title', 'merchant_name', 'reasoning'))).casefold()]
            offset, limit = int(args.get('offset', 0)), int(args.get('limit', 60))
            if offset < 0 or not 1 <= limit <= 80:
                raise ValueError('Use a nonnegative offset and limit 1..80')
            keys = ('id', 'day', 'amount_cents', 'counterparty', 'description', 'kind', 'category', 'reasoning')
            return {'total': len(rows), 'next_offset': offset + limit if offset + limit < len(rows) else None,
                    'transactions': [{**{k: r.get(k) for k in keys}, **annotation_public(r)} for r in rows[offset:offset+limit]],
                    'cached_logo_merchants': list(logo_catalog(self.ledger))}
        if name == 'transaction_annotations_write':
            items = args.get('items')
            if not isinstance(items, list) or not 1 <= len(items) <= 80:
                raise ValueError('Supply 1..80 annotations')
            saved = 0
            with self.ledger.db() as db:
                self.fenced(db)
                jobs = [dict(r) for r in db.execute("SELECT kind,payload FROM audit_jobs WHERE token=? AND state='running'", (self.token,))]
                unrestricted = any(j['kind'] in ('question', 'explanation') for j in jobs)
                allowed = {json.loads(j['payload']).get('id') for j in jobs if j['kind'] in ('enrichment', 'transaction')}
                for item in items:
                    if not unrestricted and item.get('id') not in allowed:
                        raise ValueError('Transaction is outside this audit batch')
                    saved += self.ledger.annotate(item['id'], item, 'ai', db)
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('money_summary_dirty', 'true'))
            return {'saved': saved, 'owner_annotations_preserved': len(items) - saved}
        if name == 'merchant_logo_fetch':
            merchant, domain = str(args.get('merchant_name', '')).strip(), str(args.get('domain', '')).strip().lower()
            evidence = str(args.get('evidence', '')).strip()
            if not merchant or len(merchant) > 120 or not evidence or len(evidence) > 1000:
                raise ValueError('Supply merchant name and domain evidence')
            if not re.fullmatch(r'(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain):
                raise ValueError('Supply a public merchant domain, without paths or credentials')
            with self.ledger.db() as db:
                known = db.execute('SELECT domain FROM merchant_logos WHERE merchant_name=?', (merchant,)).fetchone()
                if known and known['domain'] == domain and not args.get('refresh'):
                    return {'merchant_name': merchant, 'cached': True, 'domain': domain}
            # Only a merchant domain goes to the favicon provider, never a bank row or account.
            url = 'https://www.google.com/s2/favicons?' + urllib.parse.urlencode({'domain': domain, 'sz': 128})
            data = self.fetch(url)
            if len(data) > 32768 or len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
                raise ValueError('The provider did not return a bounded PNG logo')
            width, height = struct.unpack('>II', data[16:24])
            if not 8 <= width <= 256 or not 8 <= height <= 256:
                raise ValueError('Logo dimensions are outside 8..256 pixels')
            uri = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
            with self.ledger.db() as db:
                self.fenced(db)
                db.execute('INSERT OR REPLACE INTO merchant_logos VALUES(?,?,?,?,?,?)',
                           (merchant, domain, uri, evidence, url, self.ledger.clock()))
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('money_summary_dirty', 'true'))
            return {'merchant_name': merchant, 'cached': False, 'domain': domain, 'pixels': [width, height]}
        if name == 'enhancement_status':
            rows = self.ledger.transactions()
            return {'transactions': len(rows), 'enhanced': sum(bool(r.get('annotation_by')) for r in rows),
                    'missing': sum(not r.get('annotation_by') for r in rows), 'logos': list(logo_catalog(self.ledger))}
        raise ValueError('Unknown Money tool')


def tool_list():
    from .agent import ENRICHMENT
    def tool(name, description, properties, required=(), read=False):
        return {'name': name, 'description': description,
                'inputSchema': {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False},
                'annotations': {'readOnlyHint': read, 'destructiveHint': False, 'openWorldHint': name == 'merchant_logo_fetch'}}
    return [tool('transactions_search', 'Search ALL live imported transactions, including past months. Page until next_offset is null. missing_only finds rows without saved enhancements.',
                 {'query': {'type': 'string'}, 'missing_only': {'type': 'boolean'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}, read=True),
            tool('transaction_annotations_write', 'Save titles, merchant names, notes and tags immediately. Leaves bank facts and accounting unchanged. Use null brand ID for brands outside the supplied catalog; downloaded logos match merchant_name independently.',
                 {'items': {'type': 'array', 'items': ENRICHMENT}}, ('items',)),
            tool('merchant_logo_fetch', 'Fetch and cache a real merchant website icon for merchant_name. Supply the known public brand domain and evidence linking it to the merchant. Reuse across transactions; never invent domains or assign logos to private people. Returns an error if unavailable; use monogram fallback then.',
                 {**{k: {'type': 'string'} for k in ('merchant_name', 'domain', 'evidence')}, 'refresh': {'type': 'boolean'}}, ('merchant_name', 'domain', 'evidence')),
            tool('enhancement_status', 'Count SAVED enhancements and cached merchant logos. Verify before claiming completion.', {}, read=True)]


def serve(tools, source=sys.stdin, target=sys.stdout):
    for line in source:
        request = None
        try:
            request = json.loads(line)
            method, params = request.get('method'), request.get('params', {})
            if 'id' not in request:
                continue
            if method == 'initialize':
                result = {'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                          'capabilities': {'tools': {}}, 'serverInfo': {'name': 'money-specialist', 'version': '1.0.0'}}
            elif method == 'ping': result = {}
            elif method == 'tools/list': result = {'tools': tool_list()}
            elif method == 'tools/call':
                try:
                    value = tools.call(params['name'], params.get('arguments') or {})
                    result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}], 'isError': False}
                except Exception as error:
                    result = {'content': [{'type': 'text', 'text': str(error)}], 'isError': True}
            else:
                target.write(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Method not found'}})+'\n');target.flush();continue
            response = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
        except Exception:
            response = {'jsonrpc': '2.0', 'id': request.get('id') if isinstance(request, dict) else None,
                        'error': {'code': -32700, 'message': 'Invalid request'}}
        target.write(json.dumps(response, ensure_ascii=False)+'\n');target.flush()


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--lease')
    args = parser.parse_args()
    ledger=Ledger(Path(args.ledger))
    token=args.lease
    if not token:
        with ledger.db() as db:
            token=db.execute('SELECT lease_token FROM audit_state WHERE id=1').fetchone()['lease_token']
    serve(MoneyTools(ledger, token))


if __name__ == '__main__':
    main()
