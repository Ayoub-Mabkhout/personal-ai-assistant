# Repository and private vault

Public reusable software and ignored private data share this filesystem checkout.
The GitHub repository is public. Git ignore rules are not encryption or a secret
scanner. Separate private originals, credential references, and machine state.

```text
src/personal_assistant/       Calendar, relay, worker, mail, lab and dashboard
apps/android/                Native phone companion
apps/dashboard/              Generic HTML; private facts loaded at runtime
infra/server/                Relay and HTTPS deployment
skills/                      Portable agent skills, one folder per capability
scripts/                     Executable maintenance and common routines
config/                      Public templates and layout
config/local/                Private config/env overrides (ignored)
docs/ tests/                 Documentation and isolated tests
private/                     Entire private vault ignored
  profile/                   Index, preferences, themes and original sources
  documents/
    inbox/ contracts/
    banking/statements/      Additional bank folders are private config
    tax/ insurance/ housing/ identity/ health/
    academic/thesis/ academic/coursework/
    career/cvs/ career/cover-letters/ career/applications/
    work/ receipts/ archive/
  auth/                      Account metadata and credential references
  exports/ backups/          Private outputs and encrypted backup packages
state/                       Entire runtime tree ignored
  CONTEXT.md                 Continuity and actual implementation status
  source-conversation.md     Recovered transcript
  source-thread-records.json Recovered tool records
  calendar.sqlite3           Existing live calendar; path preserved
  queue/ runs/ logs/          Deployment/acceptance records; service ledger is OS-local
  connectors/ cache/         Sync cursors and rebuildable intermediates
```

The native Android companion and relay/HTTPS/voice deployment files are
implemented; handset verification and wake-model quality remain separate checks.
See docs/server-deployment.md for validation and host setup.
Worker, mail connectors, lab and dashboard modules are implemented. Service data,
mail objects and per-task environments stay in a private per-user directory
outside OneDrive. Keep Android-native code under apps/android. Common domain
routines use scripts with descriptive names; do not duplicate business logic.

## Profile and documents

Store confirmed facts with source/date in PROFILE.md; operating preferences in
PREFERENCES.md. Add finance, study, household, career and other domain details as
useful. Unknowns stay unknown. This cannot be a complete profile until the user
provides missing facts. Link original documents rather than copying entire
documents into prompts.

Preserve imported originals. Prefer `YYYY-MM-DD__issuer__type__reference__hash.ext` and
year subfolders as collections grow. Mail ingestion now keeps source account/
message references, original names, checksums and status in a catalog with
deduplicated byte objects. Source JSON preserves provider timestamps. Initial
collected documents stay in inbox. `scripts/mail_document.py` creates deterministic
classified copies with checksums and source provenance. Extraction/OCR remains
future work.

## Credentials and OneDrive

private/auth holds provider, purpose, allowed scopes, connection status and
credential references. Never put passwords, refresh tokens or linked-device
sessions in that metadata. Use the Windows protected credential store. When
a service requires a credential file, prefer a protected external directory such
as `%LOCALAPPDATA%/PersonalAssistant/secrets`, outside this OneDrive checkout.
Cloud secrets stay on their host with restricted permissions. Environment files
belong in ignored config/local; public shape is in .env.example, which is not
automatically loaded.

This checkout is under OneDrive. Ignored files may still sync through OneDrive;
do not assume Git ignore protects credentials from that sync. Run live SQLite
stores from one local machine, not concurrent writers to a synced copy.
ASSISTANT_STATE_DIR can relocate calendar runtime outside OneDrive. Existing
calendar state was not moved in this restructuring. Worker/service databases and
mail/lab state now use private OS-local storage; calendar relocation and its
encrypted backup strategy remain separate maintenance work.

## Skills, traces and routines

Use skills/<name>/SKILL.md with name/description frontmatter and concise domain
instructions. Generic skills can be public; personal preferences belong in the
private profile. AGENTS.md routes calendar and email requests to their skills.
The Luna dispatcher receives the repository catalog and selects skills for each
worker. Selected skill bodies are injected using absolute source paths, so workers
can apply them from any working folder. Email assignments always receive the
email skill. This does not install global skills into unrelated CLI sessions.

Command logs/traces are private because they may contain message/file contents.
Plan redaction, rotation and retention; keep verified action records separate
from verbose traces. Calendar auditing works today; the cross-service command
ledger is implemented for worker queries. Explicit coding jobs capture private
traces; empty repository log folders do not imply account-wide capture.

```powershell
.venv/Scripts/python.exe scripts/bootstrap_workspace.py
.venv/Scripts/python.exe -m pip install -e '.[server,test]'
./scripts/verify.ps1
.venv/Scripts/python.exe assistant_calendar.py --help
```

Bootstrap creates missing private folders/templates without replacing files.
Private category additions belong in ignored config/local/workspace-layout.json
using the same private_directories/state_directories lists; they are created on
the next bootstrap. Individual banks and account identifiers need not enter Git.
Installation exposes assistant-calendar; the original root script remains
compatible. Verification runs the isolated test suite, the Git publication guard
and whitespace checks. Before committing, run `scripts/check_publication.py` to
check every indexed blob for private paths, credential-shaped literals, real
contact addresses and owner home paths. `--staged` limits the check to changed
index blobs; `--include-untracked` also previews new nonignored source files.
Ignored private files are never opened by this scan. CI runs the same index guard.

For an owner-specific check, keep a JSON file such as
`config/local/publication-identifiers.json` with an `identifiers` string list,
and supply `--identifiers-file` with its path. The file must be ignored and
untracked, or stored outside the checkout. Findings show file, line and rule
only. Reserved example contact domains and runtime-generated test keys are
allowed; key-shaped literals are rejected even in tests. Unknown binary files
and incomplete scans fail closed. Review remains necessary for private facts
that cannot be recognized by these rules; Git ignore alone is not protection.
