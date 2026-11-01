# Workout subapp

Workout records live in the existing authenticated relay, independently of laptop availability. The native Companion owns its local cache, active-session draft, rest timer and durable mutation outbox. The laptop runs one serial, subscription-authenticated Codex specialist with a saved session and narrative. There is no API-funded trainer fallback.

## Storage and import

`workout.sqlite3` sits beside the relay queue database. It contains versioned entities, an append-only change history, retry receipts, immutable original imports, private photo originals and the trainer conversation. Cloud volume access must have the same owner-only protection and backup treatment as other private relay data. No workout records, photos, personal programs or training context belong in the public repository.

The Strong importer reads the semicolon-separated, quoted 13-column format, including embedded newlines. It distinguishes working, warm-up (`W`), drop (`D`), failure (`F`), note and unrecognized set codes. Each source file keeps its SHA-256 and exact original bytes. Exported dumbbell weights remain per hand; they are not doubled. Workout IDs include source workout number and timestamp, so two sessions on one day remain distinct. Exercise aliases are editable. Repeated file hashes are no-ops; overlapping exports preserve existing records and report conflicting differences rather than overwriting corrections. Import preview does not write.

Separate weight-history CSV uses `measured_at,value,unit` and optional `notes,source`, with kg or lb units. An explicit timezone applies to naive source timestamps; canonical measurements retain offsets and use kg. Another tracker format needs an adapter rather than guessing its columns.

## HTTP contract

Phone prefix: `/groceries/v1/mobile/workout`, existing paired-device bearer authentication. Owner prefix: `/relay/v1/workout` externally (`/v1/workout` inside the relay), existing protected submit credential. There are no new accounts or public photo URLs.

| Method/path below either prefix | Behavior |
| --- | --- |
| `GET /changes?after=0&limit=100` | `{schema_version,items,cursor,has_more}`; change entries have `revision,kind,id,deleted,data,at,actor`. Follow pages until `has_more=false`. |
| `POST /sync` | `{operations:[{mutation_id,kind,id,base_revision,deleted,data}]}`; returns `{results:[{kind,id,revision,deleted,data,updated}]}`. Atomic batch of 1–100 operations; maximum request 2 MiB. |
| `GET /entities?kind=workout&offset=0&limit=100` | `{items,next_offset}`; at most 200 per page. `GET /entities/{kind}/{id}` includes revision and tombstones. |
| `GET /overview` | Recomputed PRs, current ranks/method/coverage, muscle scores, achievements, cardio and matched-distance bests, weight trends, sprint evidence, active/recent sessions and trainer availability. |
| `POST /imports/strong?commit=false&timezone=UTC` | Raw CSV body, at most 32 MiB. Preview by default. `commit=true` retains provenance and adds new records. `bodyweight` is the separate weight format. |
| `GET /imports/{sha256}/original` | Exact original source bytes, private download. |
| `GET /export` | Versioned JSON records, source-import reports and trainer conversation. Photo binaries and original CSVs are downloaded through their authenticated endpoints. |
| `PUT /photos/{sha256}` | Raw JPEG/PNG/WebP, correct content type, at most 8 MiB each, 512 MiB total. Stable hash makes retries idempotent. Sync a `photo` entity referencing the returned blob ID afterwards. |
| `GET /photos/{sha256}` | Private original image; no shared/public URL. Deleting the last referencing photo entity removes its original bytes from active storage. Existing backups/model session retention are separate from active-store deletion. |
| `GET /trainer/conversation?limit=100&before=TIMESTAMP` | `{items,status}`; dated question/answer turns, state, proposals and approval. Same conversation across app launches. |
| `POST /trainer/questions` | `{id,text,photos:[],photo_approval:false,context:{}}`. Selected photo IDs require approval for this request. Offline specialist rejects new requests with 409; UI should retain the draft and show unavailable. |
| `POST /trainer/{id}/approve` | Applies the entire saved proposal once; stale entity revisions reject atomically with 409. Show before/after and obtain explicit approval first. |

`kind` is one of `athlete`, `exercise`, `template`, `workout`, `sprint`, `measurement`, `recovery`, `photo`, `composition`. Exact field definitions and validations live in `workout/models.py`. Use athlete ID `self` for the owner profile. IDs use letters, numbers, `_` and `-`; a mutation ID is 8–100 characters, an entity ID is 1–100.

Client rules: generate mutation IDs when editing, persist them before any network call, retain the same payload on retries, and remove an outbox entry only after acceptance. A 409 must preserve the local edit and offer reconciliation; never overwrite the cloud automatically. A tombstone is a deletion, not a missing response. Avoid reconstructing an editable screen during background sync. Native timers should use a monotonic countdown while active plus a persisted deadline for process recovery; network success is not needed to complete a set.

`workout.blocks` records locally timed run/warm-up/exercise/rest blocks with timezone-aware starts/ends and optional planned seconds. `template.planned_blocks` and `prescription.estimated_seconds` supply editable estimates. `workout.session_changes` records one-day swaps, shortened sessions and rest/move decisions without editing the sprint/template; `status=rest` is excluded from missed-session evidence. All edits also retain their server revision journal.

For a requested upcoming-session brief, send a normal trainer question with `context={purpose:"next_session_brief",session_id:"...",revision:CURRENT_CHANGE_CURSOR}`. The completed answer appears in `/overview.next_session_brief` with `text,generated_at,session_id,status,specialist_available`. Status is `cached`, `stale`, `missing` or `unavailable`. A subsequent record change or age over 24 hours marks it stale. Reading this field never starts a model call. `/overview.body_metrics` supplies measured weight/waist/height, BMI and waist/height with dates and ready/stale/needs-input state; it does not pretend those measurements establish muscularity or a clinical body tier.

## Rankings and analytics

Liftoff inspires the progression experience: per-lift ranks, muscle overview and next-tier progress. Its proprietary scoring curves are not reproduced or claimed as equivalent. This implementation uses a small, versioned set of factual Strength Level bodyweight-ratio thresholds for barbell bench, squat, deadlift and overhead press, with male/female tables. The source population is self-selected users of that service, not the general population. Source links, methodology and limitations travel with each score. No population percentile, age or height adjustment is invented. Unsupported exercises remain unranked while retaining personal PRs.

Reference pages, checked 2026-11-01:

- [Liftoff rank methodology](https://info.liftoffrank.com/research/strength-standards)
- [Bench](https://strengthlevel.com/strength-standards/bench-press/kg), [squat](https://strengthlevel.com/strength-standards/squat/kg), [deadlift](https://strengthlevel.com/strength-standards/deadlift/kg), [press](https://strengthlevel.com/strength-standards/shoulder-press/kg)

Epley estimates apply to 2–10 reps; a single stays its recorded load. Current ranks require a completed working/failure set in the last 28 days with confirmed high effort, and measured bodyweight within the preceding 14 days or recorded for that session. Easy reconditioning sets do not establish a precise maximum. Imported historical estimates can remain uncertain, and never become today's rank or recommended load. App scores interpolate the five source ratio levels to 200/400/600/800/1000 and map to nine named tiers; this is an app-specific presentation. Aggregate and muscle scores are means of supported current lifts with explicit coverage, not overall fitness percentiles. Hiking elevation and treadmill incline remain separate dimensions when comparing cardio efforts.

Weight trends average observations per day, then average observed days in each window; minimum 3 days for 7-day and 5 days for 14-day averages. Missing days are not invented. Sprint evidence uses the selected phase/goals and distinguishes recovery-adjusted skips. It is evidence for a retrospective, not an automatic declaration that every goal succeeded.

## Specialist lifecycle

Set `workout_specialist:true` in the private laptop worker configuration. Optional keys are `workout_model` (otherwise the existing banking model/default), `workout_runtime_dir`, `workout_profile_file`, and `workout_timeout_seconds`. Profile/context files and saved session/narrative stay outside the public repository, preferably outside synced folders. Existing `python`, `codex`, `node`, `relay_url`, and protected `submit_token_file` references are reused.

The supervisor starts `python -m personal_assistant.workout.specialist --config CONFIG`. A singleton lock, serial cloud claim and renewable fenced lease prevent two simultaneous trainers. A heartbeat expires after 90 seconds, so sleeping/disconnected laptops show unavailable. The specialist's MCP exposes only workout reads. It returns proposed template/sprint changes or substitutions to uncompleted sets in an active workout; only the authenticated owner's approval endpoint can apply them. Completed sets and other recorded workout fields cannot be rewritten by a trainer proposal. Failed requests are visible, not reported as completed advice. No integration test should consume live model allowance unless explicitly necessary and authorized.

Photo analysis is gated independently per selected request. Only those originals are downloaded into a temporary analysis workspace and attached to that turn. A resulting visual-composition record cites the approved photo IDs, model, date, rough range and uncertainty. It is explicitly nonclinical. Subsequent analysis needs a new approval; stored chat context is not blanket permission to reassess earlier images. The durable narrative supports session reconstruction if the saved session becomes unavailable or exceeds its context budget.

## Release

UI is owned by the designated designer; backend contracts remain independent of styling. Integrate both branches before reserving a release version. Run import/conflict/consent/specialist tests and the native build/UI checks, then the publication guard. Use trusted signed GitHub Actions with existing protected signer/Firebase metadata, deploy the relay with a rollback snapshot, import approved private history, start the specialist and verify the exact APK/feed/hash and notification transport. A provider receipt does not prove handset installation or display.
