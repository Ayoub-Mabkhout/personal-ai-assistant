# Search, access and thread coverage

`private/auth/mail-connections.json` records connected/excluded accounts. Real
OAuth credentials live outside the repository and OneDrive. The local archive is
normally `~/.personal-assistant/mail`; query its index with the repository venv:

```powershell
.venv/Scripts/python.exe scripts/mail_query.py search --subject "rental agreement" --sender "person@example.com" --since 2026-01-01
.venv/Scripts/python.exe scripts/mail_query.py search --text "handover keys" --limit 20
.venv/Scripts/python.exe scripts/mail_query.py read --account ACCOUNT --message-id MESSAGE_ID
.venv/Scripts/python.exe scripts/mail_query.py thread --account ACCOUNT --thread-id THREAD_ID
.venv/Scripts/python.exe scripts/mail_query.py related --account ACCOUNT --message-id MESSAGE_ID
```

Search returns previews; read/thread return normalized bodies and source metadata.
The archive may contain only attachment-bearing messages and omit messages from
the same conversation. Its coverage is always reported. Refreshes index changed
source JSON incrementally. Filters are parameterized; no SQL is generated from
email content. `--archive` selects another authorized archive or a test fixture.

Live Gmail tools: search message IDs first, batch read likely matches, and read
the actual thread when supplied. Search operators include `from:`, `to:`,
`subject:`, `after:`, `before:`, `has:attachment`, `filename:` and exact phrases.
Use `in:anywhere` only when spam/trash are relevant or a normal search misses the
target. Preserve account scope. Examples:

- `from:person@example.com subject:contract after:2026/01/01`
- `"reference-123" has:attachment filename:pdf`
- `to:person@example.com in:sent` for the user's replies/style examples.

Gmail thread IDs are stronger evidence than matching subjects. For cross-thread
context, search references and participant/topic combinations, including forwarded
or newly titled conversations.
The thread tool returns a bounded number of the most recent messages (default 20).
Check the requested/returned limits before calling it a complete conversation.
Increase its supported limit when needed; if the beginning is still missing,
search older participant/topic/reference matches and read those messages directly.
Preserve the distinction between full MIME bodies and full conversation coverage.
[Gmail operators](https://support.google.com/mail/answer/7190),
[Gmail threads](https://developers.google.com/workspace/gmail/api/guides/threads).

Outlook: use the connected tool's supported search parameters, or Graph message
`$search`/`$filter` with sender, subject, dates and conversationId. Do not pass Gmail
query syntax unchanged. `$search` has its own supported message properties and
result limits; follow returned next links where supported. Preserve immutable IDs
for archive provenance. Read the actual conversation and relevant sent items.
[Graph search](https://learn.microsoft.com/en-us/graph/search-query-parameter),
[Graph messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages).

For a configured university/private IMAP mailbox, use live headless access:
`scripts/imap_mail.py check`, `search --subject "topic" --sender "sender"`, or
`read --folder "INBOX" --uid UID`, using the repository Python environment.
Credentials are Windows DPAPI-encrypted outside OneDrive; do not print or copy
them into prompts. Searches return headers first; read only relevant messages.
Select the appropriate folder for sent mail or related threads. A source identity
is account + folder + UIDVALIDITY + UID; Message-ID/References connect threads.
Reads use EXAMINE and BODY.PEEK so messages are not marked read. IMAP text search
currently supports ASCII; provider errors are not evidence of no matching mail.
Attachment names returned by read are metadata, not downloaded documents.

CLI workers explicitly enable apps and plugins while retaining their existing
ChatGPT login. The installed Gmail plugin can reuse its authorized account
connection without copying credentials. Discover its live tools and verify account
identity. If that connection is unavailable, stop the live part with a precise
access error. The snapshot index is supplementary. An independent background
crawler may use a registered Gmail/Graph OAuth client as described in
`docs/mail-ingestion.md`; don't extract connector tokens from app/browser internals.
Failed authorization is not evidence that a searched message is absent.
