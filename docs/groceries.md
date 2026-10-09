# Phone shopping and recipes

The existing cloud relay hosts `/groceries/` and the private SQLite grocery store.
The laptop is not part of the path for shopping changes. No extra hosting service
or subscription is needed. Standalone owner login uses a Secure HttpOnly session cookie; the native phone
uses its paired credential and calls the grocery API directly.

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

The dashboard uses this same cloud grocery store. Retired shopping stores must
be inspected and explicitly migrated before their recovery data is deleted.

The preferred REWE branch is private deployment configuration. Product links open
REWE search. Store identity is verified; catalog matching and branch availability
are not. A market-aware product search still needs supported access and testing.

Validated: concurrent retry, transactional rollback, stale edits, private API
access, authenticated Assist with the worker paused, mobile layout, offline add
and reload, reconnection without duplicates, and recipe ingredients. Phone
microphone recognition and installation on the actual handset need user testing.
