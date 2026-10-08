# Background document collection and mail follow-ups

Maintenance submits bounded email jobs through the existing cloud agent queue and
persistent Luna dispatcher. Workers use the live connected Gmail plugin with the
email skill. This reuses ChatGPT authorization; it does not harvest connector
credentials or require an independent OAuth client. Only explicitly configured
connected accounts are eligible. Outlook still requires a working connection.

`scripts/mail_automation.py --config PRIVATE_CONFIG --loop` polls once per minute.
The private config follows `config/mail-automation.example.json`. A batch runs at
most every six hours by default, yielding while other prompts are queued. First
inbox coverage is the last fourteen days; successful complete pagination advances
a watermark with a forty-eight-hour overlap. Incomplete pagination retains its
exact query window and supported continuation; an absent continuation leaves the
watermark unchanged and records that limitation. This is bounded query coverage,
not a claim to have scanned all historical mail. Separate alternating batches
retrieve eight old messages with catalogued missing originals. Failed attachment
backfills retry after seven days, allowing later messages to proceed.

Jobs preserve full actual messages and request Gmail raw MIME for attachments.
The maintenance importer uses captured successful worker tool results, never
model-generated base64 or extracted previews. Truncated/missing/ambiguous raw MIME
remains pending. Originals retain checksums, source IDs and immutable archive
objects. Classified copies use deterministic names and mail-date fallback; only
an exact source excerpt permits a specialized category. Otherwise files go into
inbox. The original is never moved or overwritten. Signed artifact links and
mail traces stay in private OS-local runtime.
Individual reads and the observed Gmail batch/thread response wrappers are
supported. Only exact full/raw message objects from successful provider results
are imported; search previews, failed entries and model-authored objects are not.

The follow-up SQLite store records deadlines, renewals and awaiting replies with
the original thread/message, exact supporting excerpt, source link, certainty,
optional due date and observation time. Missing/ambiguous dates remain unknown or
tentative. Confirmed interpretations require explicit cited date wording; model
classification still merits review for consequential obligations. Awaiting-reply
observations require an outgoing request and checked thread context whose latest
message is outgoing. The observation is tentative because mailbox state can
change. Mere silence or an unread flag never proves a real unanswered request.
When a manifest lists only the other messages as context, the importer can supply
the omitted request and complete context from an actual captured full-thread
response. It never invents message IDs or infers no reply from a partial list.
Unknown message ordering or a newer incoming reply prevents that observation.
Explicit new thread evidence can resolve an observation. Dismissed/resolved items
are not automatically reopened on rescans. No email is sent, no message is marked
read, and no calendar appointment is inserted by this maintenance workflow.

Management:

```powershell
.venv/Scripts/python.exe scripts/mail_followups.py --config PRIVATE_CONFIG list
.venv/Scripts/python.exe scripts/mail_followups.py --config PRIVATE_CONFIG list --before 2026-12-31
.venv/Scripts/python.exe scripts/mail_followups.py --config PRIVATE_CONFIG resolve FOLLOWUP_ID --note "Handled"
.venv/Scripts/python.exe scripts/mail_followups.py --config PRIVATE_CONFIG dismiss FOLLOWUP_ID
```

For a dashboard, instantiate `Followups(config['followups_db'], config['archive'],
config.get('policy'))` and expose `list()` through the authenticated local UI.
Each result includes `id`, `kind`, `title`, `state`, `certainty`, `due_date`, and
`data` containing the source and quote. Never expose the SQLite file, raw trace or
all mail contents. `MailAutomation(config_path).state()` supplies last coverage,
pending task and operational results. An initially empty list is not evidence
that no obligations exist before the first successful live scan.

The local dashboard now includes a Follow-ups page and a short Today digest.
`GET /api/followups?state=open|resolved|dismissed|all` supplies concise records and
coverage. `POST /api/followups/ID` accepts `{state, note}` for Done, Dismiss and
Reopen controls. Both reuse the existing local session token and same-origin
protection. The page displays the source excerpt, original email link, due date
when known, and confirmed/needs-review status. Empty-state wording makes pending
first collection explicit. Configure `mail_automation_config` in private worker
settings, or supply `followups_db`, `mail_archive` and optional `mail_policy`
directly. No personal example records are inserted into a live store.

To integrate with the existing supervisor, add a `mail_automation_config` private
worker setting and launch the script with that path and `--loop`. Runtime logs,
config, manifests and extracted mail stay outside the public repository and
OneDrive. The maintenance loop holds a single-process lock. Idempotent queue IDs
and original checksums survive retries/restarts. Polling an existing task never
reruns it. No additional hosted service is required.

Workers read the authoritative private config and persisted batch JSON before
identity verification; delegated prose must not abbreviate addresses or query
fields. The captured Gmail profile verifies identity, rather than a model-written
boolean. Missing full-message reads cannot advance coverage. For compatibility
repair of a completed job, run `scripts/mail_automation.py --config PRIVATE_CONFIG
--repair-job TASK_ID`. This imports captured originals without a model rerun or
watermark change. A mismatched model manifest discards model-derived claims and
classifications; only captured reads with a verified account may be imported.
A profile-only trace records zero scan coverage and requires a fresh live scan.
Detailed batch instructions are saved in a private `TASK_ID-instructions.txt`.
The relay receives a compact prompt pointing to the config, batch and instructions,
keeping its 4096-character limit. `--compact-pending` repairs only an unsubmitted
local envelope and preserves the full instruction file. If an immutable local
submission already contains a different body, the helper first requires cloud
HTTP 404, then allocates a stable new ID derived from the compact prompt. The old
local envelope and original batch/manifest provenance remain intact. If the prior
task exists or lookup is unavailable, it stops without allocating a duplicate.
This helper never submits, reruns or modifies an acknowledged cloud task.
