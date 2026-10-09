# Recipes, ingredients and migration from AnyList

The cloud grocery store already holds recipes and shopping items separately.
Adding a recipe to the shopping list creates one item per ingredient and keeps
its quantity. An import saves a recipe; it does not silently add its ingredients
to the shopping list.

## Import formats

The implemented importer accepts:

- Shared recipe text with a title, an `Ingredients`/`Zutaten` section, and optional
  `Directions`, `Instructions`, `Preparation` or `Zubereitung` section.
- JSON containing a recipe or a `recipes` array with title, ingredients and steps.
- Schema.org `Recipe` JSON-LD, including recipes inside `@graph`.
- Pasted HTML containing `application/ld+json` Recipe blocks.

Ingredient lines stay separate. Simple leading quantities such as `200 g`, `½ cup`
and `1 1/2 tsp` are separated from names. Compound names such as “salt and pepper”
remain one ingredient. The importer does not estimate quantities, convert units,
scale servings or infer missing ingredients. Unmapped shared-text metadata, such
as servings, appears as a review warning and remains in the archived original.

`POST /groceries/v1/recipes/import/preview` performs no file/store writes and
returns proposed recipes, warnings and a source-content checksum. The request is
`{content, format, source}`; format defaults to `auto` and can be `text`, `json` or
`html`. Review the title, ingredients, quantities and steps before committing.

`POST /groceries/v1/recipes/import/commit` accepts the same request, parses it again,
and stores through the existing `recipe_save` mutation path. Stable recipe/import
IDs make identical retries harmless and preserve later manual edits. Editing the
content produces a different import identity; review before accepting another
version. Both endpoints require the standalone owner grocery login or the
dedicated internal grocery credential. Import size is bounded to 200 KB, 100
recipes per request, and 100 ingredients per recipe.

Raw imported input and provenance are stored beside the private grocery database
under `recipe-imports/`, with checksum filenames. They never belong in the public
repository. Recipe objects retain source references. No URL is fetched by this
importer; a recipe URL alone is not an import. Pasted HTML is parsed as data and
its scripts are not executed. Proprietary AnyList attachments are preserved as
original sources by mail filing when collected; decoding their format is not
implemented or assumed.

## Migration plan

1. Keep AnyList available during migration. Do not delete or alter its recipes.
2. Export/share one actual recipe as text first. AnyList's official help says
   sending a recipe by email or messaging includes its text and can optionally
   include a native AnyList attachment. It also documents an **Email, Print &
   AirDrop** action and a **Send Recipe** choice; menus may differ by platform.
   See [AnyList: Sending Recipes](https://help.anylist.com/articles/send-recipe/).
3. Paste that shared text into the importer. If its format lacks recognizable
   section headings, add Ingredients/Directions headings while retaining the
   original export. Preview and compare every ingredient and step with AnyList.
4. Save it and add its ingredients to the cloud shopping list. Check that each
   ingredient appears separately and quantities are retained on the phone/widget.
5. After that comparison succeeds, collect further shared recipe texts or exported
   email bodies and import them in manageable batches. The canonical JSON format
   supports batching. Do not claim AnyList provides a bulk export/API until an
   actual account export and its format have been verified.
6. Compare the recipe count, titles and a sample of ingredient/step lists; review
   every import warning. Keep original exports plus private migration receipts.
   Decide separately how to migrate any existing shopping items and checked states.
7. Use the cloud list day to day, retaining AnyList until the migration is complete
   and the owner chooses to retire it. Subscription cancellation is separate.

Native recipe-file decoding, authenticated website fetching, recipe images,
serving-based scaling and AnyList account sync are follow-on work. The current
importer requires no AnyList credentials and changes no external account.
