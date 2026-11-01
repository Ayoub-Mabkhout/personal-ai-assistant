# Train: workout cycles and persistent coaching

The Companion keeps workout drafts, exercise order, set deletion and offline edits locally. The relay owns revisioned records and history. One persistent subscription-authenticated Codex specialist reads only workout data and proposes changes; no API-funded fallback is used. The UI reports Online/Offline.

## Programs

New sprints use an ordered `cycle` of template IDs, a finite `target_sessions`, `start` and `end`. Omitted end defaults to four calendar months after start. Completed sessions advance the cycle; rest/cancelled sessions do not. There is no weekly schedule. An unfinished deadline offers extension rather than a punitive failure. `POST /sprints/{id}/extend` takes `{end,base_revision,mutation_id}` and preserves the original deadline trail. Legacy dated schedules remain readable for migration.

The coach is the primary planning interface. It generates names from goals, progress and period, drafts the next sprint, adjusts the plan and offers owner-requested active or retrospective workout corrections/deletions. All changes require owner approval and revision checks; original Strong exports and prior entity versions remain retained. Manual sprint editing is secondary. Do not turn an initial reconditioning prescription into a permanent volume ceiling.

## Tracking and metrics

No automatic between-set timer is used. A template can be started directly; users can also start the next cycle workout or an empty session. Sessions can be cancelled, edited afterwards or deleted. Canonical storage uses kg/metres/seconds, while the UI supports pounds/miles.

`overview.next_workout` has template_id, sprint_id, zero-based position, sequence_number, target_sessions, deadline and date:null (not scheduled). `exercise_stats` supplies e1rm_series and volume_series; `workout_metrics` gives total_volume_kg_reps and per-exercise estimates. A maximum from one lift is not interchangeable with another lift's maximum. Volumes use recorded external loads, including drop sets and excluding warmups; per-hand loads remain per hand. Bodyweight load is never invented.

RIR remains optional in source data. Missing RIR and RPE mean assumed RIR0 in analytics; explicit effort values take precedence. Calculations preserve originals and label assumed effort. Standard Epley estimates use2–10 reps; recorded singles remain unchanged. Four compound ranks reference versioned, explicitly named Strength Level standards, not the general population or Liftoff's proprietary score. Source links/limitations remain in each rank. Unsupported exercises keep personal records.

Running defaults to warmup in the native logger. Only completed working-tag runs establish capability. `overview.running` separates current28-day best_working, historical_best_working, recent_working and a1.5mile benchmark. Observed standard-distance times and same-pace projections have separate fields and dates; a projection is never presented as an actual effort. Warmups cannot improve current capability.

Weight history retains observed points and7-/14-day averages with sample counts. Gaps longer than7days appear in bodyweight.gaps as dashed unmeasured spans. Missing readings are not fabricated. Waist measurements are not required or used in body goals; historical raw rows remain exportable. Body goals are owner-defined weight bands, not claims about health or muscularity.

## Imports, private photos and coach

Strong imports preserve exact original bytes/hash, dates, notes, warmup/drop/failure codes and per-hand dumbbell loads. Reimports are idempotent and overlapping corrections are reported without overwriting owner edits. Weight history uses a separate import; adapt its actual exported format when supplied.

Phone endpoints use `/groceries/v1/mobile/workout` and existing pairing; owner endpoints use `/relay/v1/workout`. Entity kinds and DTOs are in models.py. `/changes` pages revision history; `/sync` atomically accepts stable mutation IDs/base revisions.409 keeps offline edits for review. `/entities`, `/overview`, `/export` and `/imports` preserve existing contracts.

Private progress-photo uploads are bounded8MiB JPEG/PNG/WebP with SHA256 IDs and authenticated downloads. Each analysis question names selected photos and explicitly approves those photos. The runner assigns trusted model/time/source-question metadata rather than trusting model-authored identifiers. Estimates are broad nonclinical ranges with uncertainty; later analyses need fresh approval. Active-store original bytes are removed when their last photo reference is deleted; backup/provider retention is separate.

The laptop supervisor enables workout_specialist using protected worker config and a private workout_profile_file/workout_runtime_dir outside synced/public storage. It stores the CLI session, narrative and private failure traces. Native Codex compaction preserves the session; aggregate multi-tool token usage is not treated as current context length. MCP dashboard reads are compact, with paged exact records for details. Real model questions share this session.

Optional auto_coach_briefs prepares a cached next-session brief only while online, after input debounce and with deduplication/cooldown. Reading a cached brief never runs the model. Photos are never analysed automatically. New clients should preserve all revision/outbox behavior, and deployments retain protected Firebase/signing configuration.
