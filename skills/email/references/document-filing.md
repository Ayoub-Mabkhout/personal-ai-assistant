# Document filing and stable names

Keep the source byte object immutable in the protected mail archive. A classified
copy belongs in the ignored document vault, normally `private/documents/`. Copies
are not credentials. The database/index stays outside OneDrive; document copies
follow the user's chosen vault location.

Categories match the repository layout: `contracts`, `banking/statements`, `tax`,
`insurance`, `housing`, `identity`, `health`, `academic/thesis`,
`academic/coursework`, `career/cvs`, `career/cover-letters`, `career/applications`,
`work`, `receipts`, `archive`, and `inbox`. Prefer a document's purpose over its
sender: a rental agreement goes to contracts; a housing appointment letter to
housing. Use inbox when content doesn't support a more specific category.

Use names of the form:

`YYYY-MM-DD__issuer__document-type__reference__sha256-prefix.ext`

Use the document's actual issue date if confirmed; otherwise use the source mail
date and record that fallback. Preserve reference/invoice numbers where known.
Omit an unknown reference. The original attachment name and all source IDs remain
in provenance metadata. Safe slugs prevent attachment names from becoming paths;
the checksum suffix distinguishes same-name documents without arbitrary counters.
Do not overwrite unrelated files. Repeated saves of the same source/category are
idempotent. A corrected classification retains the earlier source association.

```powershell
.venv/Scripts/python.exe scripts/mail_document.py --account ACCOUNT --message-id MESSAGE_ID --attachment-id ATTACHMENT_ID --category contracts --issuer "Issuer" --type rental-agreement --reference REF
```

If bytes are missing, add `--provider gmail` or `outlook` and `--credentials`
pointing to an authorized protected OAuth file. The helper validates account
identity and requested account exclusions before downloading. No password or token
belongs in command arguments. HTTP rejection or unsupported reference attachment
remains an unresolved original, not a successful save.

For a connector-downloaded original, use `--original-file ABSOLUTE_FILE`. Catalogue
the parent message and exact attachment first; the helper checks those source IDs.
Pass `--message-json ABSOLUTE_JSON` containing the exact live parent MIME message
to catalogue a message not yet in the archive. Preserve the provider's headers,
body sizes and IDs; do not reconstruct MIME content from a prose summary.
Extracted previews are not originals. An existing saved hash must match imported
bytes. Provenance and previous classifications remain in protected catalog tables.

Use exact names, account/message IDs, dates and indexed text for retrieval today.
Future vectorization should index extracted text/OCR with stable source IDs and
combine semantic retrieval with these exact filters; it is not implemented here.

Gmail attachment artifacts may return `file_uri` as an object with `download_url`,
not a URL string. `--artifact-json PROTECTED_FILE` accepts that exact structured
result and checks source IDs and size. Keep signed download metadata outside
OneDrive; do not store signed URLs in lasting document provenance.

If artifact delivery fails but Gmail itself remains authorized, its supported
`read_email(format="raw")` returns the original RFC 2822 message including MIME
attachments. This reads the same authorized mailbox through Gmail's API and needs
no artifact-host login. For reasonably sized messages, call it, then pass
`--raw-trace YOUR_OWN_EVENTS_JSONL` to the helper. Your own trace location is supplied
in worker instructions. It parses exact MIME bytes and checks the selected filename
and expected size; never copy/retype base64 through prose. `--raw-message-json`
accepts the exact saved API response as an alternative. Stop if Gmail authorization
fails. Large raw responses may need the independent OAuth download workflow.
