"""Recipe preview/import from shared text or pasted JSON-LD; never fetches a URL."""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re


MAX_CONTENT = 200_000
INGREDIENT_HEADERS = {'ingredients', 'ingredient', 'zutaten'}
INSTRUCTION_HEADERS = {'instructions', 'directions', 'method', 'preparation', 'steps', 'zubereitung', 'anleitung'}
QUANTITY = re.compile(r'^((?:\d+(?:[.,]\d+)?(?:\s+\d+/\d+)?|\d+/\d+|[¼½¾⅓⅔⅛⅜⅝⅞])'
                      r'(?:\s*[-–]\s*(?:\d+(?:[.,]\d+)?|\d+/\d+))?'
                      r'(?:\s*(?:kg|g|mg|ml|l|oz|lb|cups?|tbsp|tsp|tablespoons?|teaspoons?|'
                      r'EL|TL|Prisen?|Stück|cloves?|cans?|packs?|Packungen?))?)(?:\s+)(.+)$', re.I)


def ingredient(value):
    if isinstance(value, dict):
        result = {'name': str(value.get('name', '')).strip(), 'quantity': str(value.get('quantity', '')).strip()}
    elif isinstance(value, str):
        text = re.sub(r'^\s*[-•*]\s*', '', value).strip()
        match = QUANTITY.match(text)
        result = {'name': match[2].strip(), 'quantity': match[1].strip()} if match else {'name': text, 'quantity': ''}
    else:
        raise ValueError('Ingredients must be text lines or name/quantity objects.')
    if not result['name'] or len(result['name']) > 300 or len(result['quantity']) > 100:
        raise ValueError('Ingredient name or quantity is empty/too long.')
    return result


def instructions(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return '\n'.join(filter(None, (instructions(item) for item in value)))
    if isinstance(value, dict):
        text = value.get('text') or value.get('description') or ''
        children = value.get('itemListElement', [])
        return '\n'.join(filter(None, [instructions(text), instructions(children)]))
    if value is None:
        return ''
    raise ValueError('Recipe instructions must be text or structured instruction steps.')


def normalize(value, source=''):
    title = str(value.get('title') or value.get('name') or '').strip()
    values = value.get('ingredients') or value.get('recipeIngredient') or []
    if isinstance(values, str):
        values = [line for line in values.splitlines() if line.strip()]
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        raise ValueError('A recipe needs between one and 100 ingredients.')
    recipe = {'title': title, 'ingredients': [ingredient(item) for item in values],
              'instructions': instructions(value.get('instructions', value.get('recipeInstructions', ''))),
              'source': str(source or value.get('source') or value.get('url') or '').strip()}
    if not title or len(title) > 200 or len(recipe['instructions']) > 6000 or len(recipe['source']) > 1000:
        raise ValueError('Recipe title, instructions or source is missing/too long.')
    fingerprint = hashlib.sha256(json.dumps(recipe, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'id': 'recipe-'+fingerprint[:40], **recipe}


def json_recipes(value):
    if isinstance(value, list):
        for item in value:
            yield from json_recipes(item)
    elif isinstance(value, dict):
        types = value.get('@type', [])
        types = [types] if isinstance(types, str) else types
        if 'Recipe' in types or ('ingredients' in value and ('title' in value or 'name' in value)):
            yield value
        elif '@graph' in value:
            yield from json_recipes(value['@graph'])
        elif 'recipes' in value:
            yield from json_recipes(value['recipes'])


class RecipeHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_json = False
        self.parts = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'script' and dict(attrs).get('type', '').lower() == 'application/ld+json':
            self.in_json = True
            self.parts = []

    def handle_data(self, data):
        if self.in_json:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.in_json:
            self.scripts.append(''.join(self.parts))
            self.in_json = False


def text_recipe(content, source=''):
    lines = [line.strip() for line in content.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    if not lines:
        raise ValueError('Paste the recipe text first.')
    title = lines[0]
    mode, ingredients, directions, warnings = None, [], [], []
    for line in lines[1:]:
        heading = line.rstrip(':').casefold()
        if heading in INGREDIENT_HEADERS:
            mode = 'ingredients'
            continue
        if heading in INSTRUCTION_HEADERS:
            mode = 'instructions'
            continue
        if not line:
            continue
        if mode == 'ingredients':
            ingredients.append(line)
        elif mode == 'instructions':
            directions.append(line)
        elif re.match(r'^(?:https?://)\S+$', line):
            source = source or line
        else:
            warnings.append('Unmapped recipe metadata: '+line[:160])
    if not ingredients:
        raise ValueError('Text import needs a title followed by an Ingredients or Zutaten section. Add a Directions section for steps.')
    return normalize({'title': title, 'ingredients': ingredients, 'instructions': '\n'.join(directions)}, source), warnings


def preview_import(content, format='auto', source=''):
    if not isinstance(content, str) or not content.strip() or len(content.encode()) > MAX_CONTENT:
        raise ValueError('Recipe import must contain at most 200 KB of text.')
    if format not in ('auto', 'text', 'json', 'html'):
        raise ValueError('Unsupported recipe import format.')
    selected = format
    if format == 'auto':
        stripped = content.lstrip()
        selected = 'json' if stripped.startswith(('{', '[')) else 'html' if stripped.startswith('<') else 'text'
    warnings = []
    if selected == 'text':
        recipe, warnings = text_recipe(content, source)
        recipes = [recipe]
    else:
        if selected == 'html':
            parser = RecipeHTML()
            parser.feed(content)
            values = []
            for script in parser.scripts:
                try:
                    values.extend(json_recipes(json.loads(script)))
                except (ValueError, TypeError, RecursionError):
                    warnings.append('Ignored an invalid JSON-LD block.')
        else:
            try:
                values = list(json_recipes(json.loads(content)))
            except (ValueError, TypeError, RecursionError):
                raise ValueError('Could not read recipe JSON.') from None
        if not values or len(values) > 100:
            raise ValueError('Import needs between one and 100 Recipe records; HTML must contain Recipe JSON-LD.')
        recipes = [normalize(value, source) for value in values]
    unique = {recipe['id']: recipe for recipe in recipes}
    if len(unique) < len(recipes):
        warnings.append('Identical recipes were collapsed into one.')
    return {'recipes': list(unique.values()), 'warnings': warnings, 'format': selected,
            'sha256': hashlib.sha256(content.encode()).hexdigest(), 'count': len(unique)}


def commit_import(store, content, format='auto', source=''):
    preview = preview_import(content, format, source)
    directory = store.path.parent/'recipe-imports'
    directory.mkdir(parents=True, exist_ok=True)
    original = directory/(preview['sha256']+'.original.txt')
    try:
        descriptor = os.open(original, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if hashlib.sha256(original.read_bytes()).hexdigest() != preview['sha256']:
            raise ValueError('Archived recipe source failed its integrity check.')
    else:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content.encode())
    saved = []
    for recipe in preview['recipes']:
        # The same import is harmless even after the user later edits the recipe.
        store.mutate({'id': 'import-'+recipe['id'][7:], 'operation': 'recipe_save', 'recipe': recipe})
        saved.append(recipe['id'])
    provenance = {'sha256': preview['sha256'], 'format': preview['format'], 'source': source,
                  'recipe_ids': saved, 'warnings': preview['warnings']}
    fingerprint = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    metadata = directory/(preview['sha256']+'-'+fingerprint[:16]+'.json')
    try:
        descriptor = os.open(metadata, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump(provenance, output, ensure_ascii=False, indent=2)
    return {**preview, 'saved_ids': saved, 'saved': True}
