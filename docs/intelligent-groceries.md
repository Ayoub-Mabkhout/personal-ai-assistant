# Intelligent grocery commands

Voice requests involving list changes use a small cloud model and a strict
structured change plan, rather than sentence splitting. The same interpreter is
shared by command voice, Live/Realtime delegation and the authenticated text
endpoint. The laptop does not need to be online.

Examples: “Add three bananas and sparkling water”; “Remove milk and eggs from my
list”; “Mark the bread as bought and add oat milk instead of regular milk.”
Requests unrelated to groceries continue into the normal agent queue. Ambiguous
targets produce a question without changing the list.

The model sees only the current request and a bounded grocery snapshot. It has
no tools or access to mail, files, company data or other accounts. A strict schema
limits actions to add/delete/complete/update. Existing IDs and versions are
validated; all changes apply in one transaction. A saved interpretation and
mutation receipt prevent repeated model calls or duplicate changes on retries.
Replies describe actual committed changes, rather than model promises.

The default configurable model is `gpt-5.4-nano` with no reasoning, a 2,000-token
output limit, and the existing protected voice API key. Every attempt reserves
a conservative amount in the shared monthly API ledger, then settles reported
usage. No repeated automatic API test loop is used. Runtime configuration may
select a different model, but its pricing and reasoning support must be reviewed
before changing the default. Missing service access leaves recordings pending;
it does not silently apply a crude string split.

API: `/groceries/v1/voice` accepts an authenticated request ID and text. Native
voice continues through `/groceries/v1/mobile/voice` and its paired credentials.
No personal information or provider credentials belong in tracked configuration.
