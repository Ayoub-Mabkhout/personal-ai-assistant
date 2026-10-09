# Scheduled grocery matching

The cloud relay can check the selected REWE market every 12 hours, independently
of the laptop. Enable it with a private `/data/rewe-check.json` based on
`config/rewe-check.example.json`. Store identifiers and addresses are runtime
configuration. There are no model calls, additional hosting services, purchases,
or automatic substitutions.

The schedule and last result persist in the grocery database across deployments.
Only incomplete items are considered. Matching handles case, repeated spaces,
joined ingredient words, and a conservative German/English synonym dictionary.
Every requested qualifier must still match; fuzzy spelling does not discard
allergy, dietary, or brand constraints. A changed item name invalidates its old
match without changing the item version or disrupting offline edits.

The public market page supplies some advertised offers, not a complete inventory.
Matches from current store-scoped offers are labelled **REWE · listed for your
store**, with source, product, timestamp and expiry. **Available in REWE** requires
explicit current stock evidence. Failure to match never means out of stock.
Expired offers, access errors and failed checks remove positive badges rather
than preserving unsupported claims. Shelf stock is not inferred from a national
catalogue or a search result.

HTTP 401/403 is recorded as `access_required`; the checker waits until the next
scheduled run instead of retrying repeatedly. A supported authenticated catalogue
or retailer-authorized data source is needed if the public page blocks access.
It does not bypass challenges, scrape account data, or pretend access succeeded.
The grocery snapshot includes `retailer_check` status and matching items include
`retailer` evidence. These remain private authenticated API responses.
