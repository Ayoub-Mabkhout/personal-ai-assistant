"""Bounded, model-free retailer checks. Catalogue evidence is not stock evidence."""
import hashlib
import html
import json
from pathlib import Path
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


ALIASES = (
    ('banane', 'banana', 'bananas', 'bananen'),
    ('milch', 'milk'), ('joghurt', 'yogurt', 'yoghurt'),
    ('sprudelwasser', 'sparkling water', 'sparklingwater', 'wasser mit kohlensäure'),
    ('stilles wasser', 'still water'), ('frühlingszwiebeln', 'spring onions', 'scallions'),
    ('kartoffeln', 'potatoes', 'potato'), ('tomaten', 'tomatoes', 'tomato'),
    ('gurke', 'cucumber', 'cucumbers'), ('haferdrink', 'oat milk', 'hafermilch'),
    ('eier', 'eggs', 'egg'), ('butter',), ('erdbeeren', 'strawberries'),
)


def normalize(value):
    value = unicodedata.normalize('NFKD', value.casefold().replace('ß', 'ss'))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', ''.join(c for c in value if not unicodedata.combining(c))).split())


def canonical(value):
    value = normalize(value)
    for group in ALIASES:
        target = normalize(group[0])
        for alias in sorted(group, key=len, reverse=True):
            term = normalize(alias)
            for variant in (term, term.replace(' ', '')):
                value = re.sub(r'(?<!\w)' + re.escape(variant) + r'(?!\w)', target, value)
    return value


def matches(query, title):
    """Require every requested ingredient/qualifier; do not fuzzy-match allergies away."""
    left, right = canonical(query), canonical(title)
    return bool(left) and set(left.split()) <= set(right.split())


def public_market_catalog(config, now):
    url = config['market_url']
    parsed = urllib.parse.urlsplit(url)
    market = str(config['market_id'])
    if parsed.scheme != 'https' or parsed.hostname != 'www.rewe.de' or parsed.username or parsed.password or not re.fullmatch(r'[0-9]+', market) or ('/' + market + '/') not in parsed.path:
        raise ValueError('Configure the official HTTPS page for the selected REWE market.')
    request = urllib.request.Request(url, headers={'User-Agent': 'PersonalAssistant-RetailerCheck/1.0', 'Accept': 'text/html'})
    with urllib.request.urlopen(request, timeout=15) as response:
        if urllib.parse.urlsplit(response.url).hostname != 'www.rewe.de':
            raise ValueError('Unexpected retailer redirect.')
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError('Retailer page exceeds the response limit.')
    page = body.decode('utf-8')
    plain = html.unescape(re.sub('<[^>]*>', ' ', page))
    until = re.search(r'Gültig\s+diese\s+Woche\s+bis\s+\w+,?\s*(\d{1,2}\.\d{1,2}\.\d{4})', plain, re.I)
    if not until:
        raise ValueError('No current store-scoped offer period was supplied.')
    from zoneinfo import ZoneInfo
    deadline = datetime.strptime(until.group(1), '%d.%m.%Y').replace(hour=23, minute=59, second=59, tzinfo=ZoneInfo(config.get('timezone', 'Europe/Berlin'))).timestamp()
    if deadline < now:
        raise ValueError('The retailer returned expired offers.')
    products = []
    for found in re.finditer(r'<h3\b[^>]*>(.*?)</h3>(.*?)(?=<h3\b|$)', page, re.I | re.S):
        name = ' '.join(html.unescape(re.sub('<[^>]*>', ' ', found.group(1))).split())
        tail = html.unescape(re.sub('<[^>]*>', ' ', found.group(2)))[:1200]
        if name and re.search(r'\d+[,.]\d{2}\s*€', tail):
            products.append({'name': name[:300], 'url': url, 'state': 'listed', 'valid_until': deadline})
    if not products:
        raise ValueError('No usable store-scoped products were supplied.')
    return products


class RetailerCheck:
    def __init__(self, groceries, config, clock=time.time, fetch=public_market_catalog):
        self.store, self.config, self.clock, self.fetch = groceries, config, clock, fetch
        self.stop = threading.Event()
        self.thread = None
        self.interval = max(3600, int(config.get('interval_seconds', 43200)))
        with self.store.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS retailer_status (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, next_check REAL NOT NULL); CREATE TABLE IF NOT EXISTS retailer_matches (item_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, body TEXT NOT NULL);')

    def run_once(self):
        now = self.clock()
        with self.store.db() as db:
            row = db.execute('SELECT next_check FROM retailer_status WHERE id=1').fetchone()
            if row and row[0] > now:
                return False
            items = [dict(r) for r in db.execute('SELECT id,name FROM items WHERE complete=0')]
        status = {'retailer': 'REWE', 'checked_at': datetime.fromtimestamp(now, timezone.utc).isoformat(), 'state': 'checked', 'matched': 0, 'stock_verified': False}
        records = []
        try:
            if not items:
                status['state'] = 'empty'
            else:
                products = self.fetch(self.config, now)
                for item in items:
                    candidates = [p for p in products if matches(item['name'], p['name'])]
                    # A positive stock claim needs explicit provider evidence. Public offers only show listing.
                    product = next((p for p in candidates if p.get('state') == 'available'), candidates[0] if candidates else None)
                    if product:
                        state = 'available' if product.get('state') == 'available' and product.get('stock_verified') is True else 'listed'
                        record = {'retailer': 'REWE', 'state': state, 'product': product['name'], 'source': product['url'], 'checked_at': status['checked_at'], 'expires_at': min(float(product['valid_until']), now + self.interval * 2), 'stock_verified': state == 'available'}
                        records.append((item['id'], hashlib.sha256(item['name'].encode()).hexdigest(), json.dumps(record)))
                status['matched'] = len(records)
        except urllib.error.HTTPError as error:
            status.update(state='access_required' if error.code in (401, 403) else 'unavailable', http_status=error.code)
        except (OSError, ValueError, KeyError, TypeError):
            status['state'] = 'unavailable'
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM retailer_matches')
            db.executemany('INSERT INTO retailer_matches VALUES(?,?,?)', records)
            db.execute('INSERT OR REPLACE INTO retailer_status VALUES(1,?,?)', (json.dumps(status), now + self.interval))
        return status

    def start(self):
        if self.thread:
            return
        def run():
            while not self.stop.is_set():
                try: self.run_once()
                except Exception: pass  # Retry on the next bounded poll, never crash notification delivery.
                self.stop.wait(60)
        self.thread = threading.Thread(target=run, name='retailer-check', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=20)
