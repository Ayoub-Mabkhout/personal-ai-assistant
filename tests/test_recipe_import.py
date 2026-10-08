import json
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from personal_assistant.groceries.recipes import preview_import, commit_import
from personal_assistant.groceries.store import Groceries


TEXT = '''Pasta with tomatoes
Serves 2
Ingredients:
200 g pasta
2 tomatoes
- salt and pepper
Directions:
Cook the pasta.
Add tomatoes and season.
'''


class RecipeImportTests(unittest.TestCase):
    def test_import_api_requires_login_and_preview_does_not_commit(self):
        from personal_assistant.groceries.api import router
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'groceries.db'
            app = FastAPI()
            app.include_router(router(path, 'g'*48, 'http://unused', Path(temporary)))
            client = TestClient(app)
            request = {'content': TEXT, 'source': 'AnyList shared recipe'}
            base = '/groceries/v1/recipes/import/'
            self.assertEqual(client.post(base+'preview', json=request).status_code, 401)
            headers = {'Authorization': 'Bearer '+'g'*48}
            response = client.post(base+'preview', json=request, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['count'], 1)
            self.assertEqual(Groceries(path).snapshot()['recipes'], [])
            self.assertEqual(client.post(base+'commit', json=request, headers=headers).status_code, 200)
            self.assertEqual(client.post(base+'commit', json=request, headers=headers).status_code, 200)
            self.assertEqual(len(Groceries(path).snapshot()['recipes']), 1)
            self.assertEqual(client.post(base+'preview', json={'content':'Not a recipe'}, headers=headers).status_code, 422)

    def test_shared_text_preserves_compound_ingredients_and_warns_about_metadata(self):
        result = preview_import(TEXT)
        self.assertEqual(result['format'], 'text')
        recipe = result['recipes'][0]
        self.assertEqual(recipe['ingredients'], [{'name':'pasta','quantity':'200 g'},
            {'name':'tomatoes','quantity':'2'}, {'name':'salt and pepper','quantity':''}])
        self.assertIn('Serves 2', result['warnings'][0])
        self.assertIn('Add tomatoes', recipe['instructions'])
        with self.assertRaisesRegex(ValueError, 'Ingredients'):
            preview_import('Title\n200 g pasta\nCook it')

    def test_recipe_jsonld_graph_and_structured_steps(self):
        value = {'@context':'https://schema.org', '@graph':[{'@type':'WebPage'},
                 {'@type':['CreativeWork','Recipe'], 'name':'Soup',
                  'recipeIngredient':['½ cup rice','1 1/2 tsp salt'],
                  'recipeInstructions':[{'@type':'HowToSection','itemListElement':[
                      {'@type':'HowToStep','text':'Cook rice.'}, {'text':'Season.'}]}],
                  'url':'https://example.org/soup'}]}
        markup = '<html><script type="application/ld+json">'+json.dumps(value)+'</script></html>'
        recipe = preview_import(markup)['recipes'][0]
        self.assertEqual(recipe['title'], 'Soup')
        self.assertEqual(recipe['ingredients'][0], {'name':'rice','quantity':'½ cup'})
        self.assertEqual(recipe['ingredients'][1], {'name':'salt','quantity':'1 1/2 tsp'})
        self.assertEqual(recipe['instructions'], 'Cook rice.\nSeason.')
        self.assertEqual(recipe['source'], 'https://example.org/soup')
        self.assertEqual(preview_import(json.dumps(value))['recipes'][0], recipe)

    def test_batch_dedup_limits_and_plain_html_rejection(self):
        record = {'title':'Eggs', 'ingredients':[{'name':'eggs','quantity':'2'}]}
        result = preview_import(json.dumps({'recipes':[record, record]}))
        self.assertEqual(result['count'], 1)
        self.assertIn('collapsed', result['warnings'][0])
        with self.assertRaisesRegex(ValueError, 'JSON-LD'):
            preview_import('<h1>Eggs</h1><p>2 eggs</p>')
        with self.assertRaises(ValueError):
            preview_import('x'*200001)
        with self.assertRaises(ValueError):
            preview_import(json.dumps({'title':'Empty','ingredients':[]}))

    def test_preview_has_no_writes_commit_retry_and_recipe_add_separate_items(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Groceries(Path(temporary)/'groceries.db')
            preview = preview_import(TEXT, source='AnyList shared recipe')
            self.assertEqual(store.snapshot()['recipes'], [])
            self.assertFalse((Path(temporary)/'recipe-imports').exists())
            result = commit_import(store, TEXT, source='AnyList shared recipe')
            repeated = commit_import(store, TEXT, source='AnyList shared recipe')
            self.assertEqual(result['saved_ids'], repeated['saved_ids'])
            self.assertEqual(len(store.snapshot()['recipes']), 1)
            self.assertEqual(store.snapshot()['items'], [])
            original = Path(temporary)/'recipe-imports'/(preview['sha256']+'.original.txt')
            self.assertEqual(original.read_text(), TEXT)
            self.assertEqual(len(list(original.parent.glob('*.json'))), 1)
            recipe = store.snapshot()['recipes'][0]
            changed = {key:value for key,value in recipe.items() if key!='version'}
            changed['title'] = 'Edited title'
            store.mutate({'id':'manual-edit-test', 'operation':'recipe_save', 'recipe':changed, 'version':recipe['version']})
            commit_import(store, TEXT, source='AnyList shared recipe')
            self.assertEqual(store.snapshot()['recipes'][0]['title'], 'Edited title')
            store.mutate({'id':'add-recipe-test', 'operation':'recipe_add', 'target':recipe['id']})
            self.assertEqual([item['name'] for item in store.snapshot()['items']], ['pasta','tomatoes','salt and pepper'])


if __name__ == '__main__':
    unittest.main()
