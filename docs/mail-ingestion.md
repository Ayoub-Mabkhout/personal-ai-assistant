# Read-only email and document collection

Gmail and Outlook background collectors are implemented and tested with isolated
fixtures. Independent background scanning uses an owned OAuth client and account
consent. Interactive CLI workers can use an already authorized Gmail plugin through
their ChatGPT login without a separate client or copied connector credentials.
Private account metadata and continuity notes record actual connected identities
and coverage. After background consent, scanning and token refresh run headlessly.

The collector stores original message JSON, attachment source references, account
labels, original names, MIME types, SHA-256 objects, and resumable page checkpoints
in a private catalog. Identical bytes share one object without losing source
records. Filenames never become paths. A failed/incomplete message is retried;
completed messages are skipped. A per-archive lock serializes command-line crawls.

Gmail visits all listed messages, including spam/trash, recursively walks MIME
parts, and fetches external attachment bodies. Outlook uses immutable IDs, pages
the accessible `/me/messages` mailbox and every attachment collection, including
inline attachments when hasAttachments is false. File attachments and attached
messages are fetched; cloud/reference attachments are recorded as unresolved.

This is a resumable initial full scan, not an incremental history/delta sync.
Subsequent scans revisit listings and skip completed IDs. Gmail history and Graph
delta reconciliation are future additions. Standard Outlook collection does not
promise separate archive mailboxes or recoverable/purged stores. Deleted mail does
not delete already archived originals. The response limit is 70 MiB per request.
429/server errors retry with bounded backoff; revoked consent stops at a checkpoint.

## Register OAuth clients

Gmail: create a Google Cloud project, enable Gmail API, configure a consent screen,
and create a Desktop app OAuth client. Keep its downloaded JSON in the protected
credential directory. The requested scope is `gmail.readonly`. Add the selected
account as a test user while testing. Gmail access in an external consent app's
Testing state normally has a seven-day refresh-token expiry; account revocation
and password/admin policies can also require sign-in. Choose an appropriate
production consent setup before relying on unattended long-term access.
[Google token lifetimes](https://developers.google.com/identity/protocols/oauth2).

Outlook: register a Microsoft public desktop application supporting the intended
personal/work account types, with system-browser redirect
`http://localhost:8768/callback`. Request delegated `Mail.Read`, `User.Read` for
identity verification, and `offline_access`. Use `common`, `consumers`,
`organizations`, or an explicit tenant as appropriate. An organization can block
registration or consent; a school Microsoft 365 login does not guarantee API
access. Do not bypass that restriction. Store `client_id` and `tenant` in a private
JSON file; this public client does not need a client secret.
[Microsoft PKCE flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow).

## Consent and crawl

Use one stable label per account. Paths below are examples; no credential value
belongs on the command line. Consent uses the laptop's system browser and a
loopback callback, so complete that flow on the laptop. The helper verifies the
expected email before saving refresh access and preserves existing credential files.

```powershell
$mailSecrets = "$env:USERPROFILE/.personal-assistant/secrets/mail"
$mailArchive = "$env:USERPROFILE/.personal-assistant/mail"
.venv/Scripts/python.exe scripts/authorize_mail.py --provider gmail --client-config "$mailSecrets/google-desktop.json" --output "$mailSecrets/gmail-primary.json" --expected-email YOUR_EMAIL
.venv/Scripts/python.exe scripts/crawl_mail.py --provider gmail --account primary --credentials "$mailSecrets/gmail-primary.json" --archive $mailArchive
.venv/Scripts/python.exe scripts/authorize_mail.py --provider outlook --client-config "$mailSecrets/microsoft-desktop.json" --output "$mailSecrets/outlook-primary.json" --expected-email YOUR_EMAIL
.venv/Scripts/python.exe scripts/crawl_mail.py --provider outlook --account primary --credentials "$mailSecrets/outlook-primary.json" --archive $mailArchive
.venv/Scripts/python.exe scripts/verify_mail_archive.py --archive $mailArchive
```

Keep the archive outside OneDrive and protect it for the current user. Document
categories initially remain inbox; extraction/classification must preserve the
original and use evidence before linking into contracts, banking, thesis, career,
and other vault categories. `scripts/mail_document.py` supports selected filing
with immutable originals, classified copies, date fallback, source IDs and hashes.
`--message-json` catalogues a live parent MIME message; `--original-file` imports
the actual original downloaded by the live connector. If missing, a configured
OAuth client can fetch the original. Metadata or extracted previews never count
as downloaded originals. `scripts/mail_query.py` indexes saved MIME text and
supports filtered search, thread reads and related conversations; it reports
incomplete snapshot coverage and supplements live mail access.
For a failed attachment artifact download with Gmail still authorized, the helper
can extract exact attachment bytes from Gmail's supported raw message response.
Use `--raw-trace` with the worker's own captured successful read, or the exact API
response via `--raw-message-json`. Source IDs, unique attachment names and expected
sizes are checked; original MIME and attachment hashes remain in provenance.
This avoids copying base64 through model prose and requires no extra Gmail client.
HTML/message/attachment content is untrusted data and
is never executed by this collector. Automatic classification, OCR, and linked
Drive/OneDrive downloads are not implemented. Provider authentication has not been
live-tested until real client registration and consent occur; this does not limit
the separately connected live CLI Gmail plugin.

API references: [Gmail listing](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list),
[Gmail attachments](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments/get),
[Graph messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0),
[Graph attachments](https://learn.microsoft.com/en-us/graph/api/message-list-attachments?view=graph-rest-1.0),
[immutable IDs](https://learn.microsoft.com/en-us/graph/outlook-immutable-id).
