---
name: send-to-phone
description: Find a file the user asked for (on the laptop, or an email attachment) and send it to the paired Companion phone, where it is saved to Downloads with a "File ready" notification that opens it.
---

# Send a file to the phone

Use this skill when the user asks to get, send, fetch or download a specific file
"to my phone", "on my phone", or simply "send me the March invoice PDF" or "get me
the slides from my thesis folder" from the phone. Resolve `scripts/` and `docs/`
against the repository path supplied in worker instructions.

## Find the file

Search only for what was asked. Use names, folders, dates, extensions and content
hints from the request, prefer the most specific location, and avoid sweeping the
whole disk or reading unrelated private files. For a file received by email, use the
email skill to locate the message and save only that attachment to the task
directory first. If several candidates fit equally, or none fits, return
`needs_input` with a short list (name, folder, date, size) instead of guessing.
Never send a different file than the one identified, and never send credentials,
key files or whole folders unless the user explicitly named them. Zip a folder only
when the user asked for the folder.

## Send it

```powershell
.venv/Scripts/python.exe scripts/send_to_phone.py "ABSOLUTE_FILE_PATH" --note "SHORT_CONTEXT" --id TASK_ID-file-1
```

- `--id`: stable per requested file, derived from the task ID and file index. Reuse
  it on every retry. Omitted, the ID is derived from name, content and note, so a
  repeated call cannot duplicate the file. An ID that was already delivered is
  reported back (`created_now: false`) and is never sent again; for a deliberate
  second copy the user asked for, use a new ID.
- `--name` changes the name shown on the phone; `--note` (max 300 characters) is the
  notification text, e.g. "From Documents/Invoices, 12 March".
- `--phone ID` is needed only when more than one phone is paired; `--list-phones`
  shows them and the size limit. `--status ID` reports a transfer's saved state.
- The relay limit is 50 MiB by default. For a larger file, say so and offer a
  smaller export (for example a PDF instead of the source document) rather than
  splitting it unasked.

The helper reads the protected worker config; no credential goes on the command
line. It prints the relay record and appends to `file-drops.jsonl` in the agent
runtime directory.

## Report accurately

`state: ready` means stored on the relay and announced to the phone, not yet on the
phone. `delivered` means the phone verified the checksum, saved it and confirmed;
the relay copy is then deleted. `expired` or `cancelled` means it never arrived.
Report the file name, its source path and the actual state. Do not claim the user
has seen it. Background scans and other skills must not send files on their own;
send only files the user requested in this task.

Contracts and deployment: `docs/native-companion.md` (Files to the phone).
