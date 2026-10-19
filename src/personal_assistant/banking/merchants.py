"""Curated merchant identities; no model-supplied URLs or remote logo lookup."""
import re
import unicodedata

BRAND_CATALOG = {
    'dm': {'name': 'dm', 'domain': 'dm.de', 'aliases': ['dm', 'dm drogeriemarkt', 'dm drogerie markt']},
    'rewe': {'name': 'REWE', 'domain': 'rewe.de', 'aliases': ['rewe']},
    'aldi': {'name': 'ALDI', 'domain': 'aldi-sued.de', 'aliases': ['aldi']},
    'lidl': {'name': 'Lidl', 'domain': 'lidl.de', 'aliases': ['lidl']},
    'amazon': {'name': 'Amazon', 'domain': 'amazon.de', 'aliases': ['amazon', 'amzn']},
    'uber': {'name': 'Uber', 'domain': 'uber.com', 'aliases': ['uber']},
    'deutsche-bahn': {'name': 'Deutsche Bahn', 'domain': 'bahn.de', 'aliases': ['deutsche bahn', 'db vertrieb', 'db fernverkehr', 'db regio', 'db bahn']},
    'paypal': {'name': 'PayPal', 'domain': 'paypal.com', 'aliases': ['paypal']},
    'rossmann': {'name': 'Rossmann', 'domain': 'rossmann.de', 'aliases': ['rossmann']},
}


def normalized(text):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKD', text.lower()).encode('ascii', 'ignore').decode()).split())


def supported_brand(brand, source):
    """A logo needs a bounded alias in original bank evidence, not a generated title."""
    if brand not in BRAND_CATALOG:
        return False
    source = ' ' + normalized(source) + ' '
    return any(' ' + normalized(alias) + ' ' in source for alias in BRAND_CATALOG[brand]['aliases'])
