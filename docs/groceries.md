# Phone shopping and recipes

The existing cloud relay hosts `/groceries/` and the private SQLite grocery store.
The laptop is not part of the path for shopping changes. No extra hosting service
or subscription is needed. Home Assistant owns login; the phone signs in through
its OAuth flow, refreshes access tokens, and calls the grocery API directly.

Open the grocery URL in Chrome on Android and choose **Add to home screen** or
**Install app**. The list and recipes have light and dark modes. Enter several
items separated by commas or “and”. Bought items remain in a collapsible section.
Recipe ingredients are separate entries when added to the list. Paste ingredients
from an AnyList recipe shared as text; no AnyList account token is required.
Recipe import now previews shared text or recipe JSON/HTML before saving.
Select individual ingredients to add. See [AnyList migration](anylist-migration.md).
A native [shopping widget](phone-companion.md) is built; handset installation
and verification remain pending. Automatic AnyList synchronization is not configured.

The phone retains a cached list and a durable mutation outbox. An offline addition
survives a reload and replays when the app reconnects or opens again. Android may
suspend a web app in the background, so this is not a promise of immediate sync
while the app is closed. The UI distinguishes cloud confirmation from phone-only
storage. Rejected edits stay in a review section rather than disappearing.
The service worker caches public assets only; private API responses are not placed
in its HTTP cache. Signing out leaves the local list on that device.

Each mutation has an immutable request ID and content fingerprint. Changes and
acknowledgements commit together. Retrying the same request returns the original
result; reusing its ID with different content returns a conflict. Item and recipe
versions reject stale edits. List additions intentionally remain separate entries;
no quantity merging guesses are made.

Home Assistant's `todo.groceries` is a view of the same store, exposed by the
`assistant_groceries` integration. Assist's custom sentence “add bananas and
sparkling water to my shopping list” calls the cloud service directly and splits
the items. The older native `todo.shopping_list` is preserved as a legacy list;
do not build new clients against it. Existing legacy entries must be migrated
explicitly if any are added there. The custom integration uses a dedicated
server-side secret, never the phone's login token or the laptop worker credential.

The preferred REWE branch is private deployment configuration. Product links open
REWE search. Store identity is verified; catalog matching and branch availability
are not. A market-aware product search still needs supported access and testing.

Validated: concurrent retry, transactional rollback, stale edits, private API
access, authenticated Assist with the worker paused, mobile layout, offline add
and reload, reconnection without duplicates, and recipe ingredients. Phone
microphone recognition and installation on the actual handset need user testing.
