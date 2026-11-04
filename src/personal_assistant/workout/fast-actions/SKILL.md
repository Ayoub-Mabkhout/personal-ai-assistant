---
name: workout-fast-actions
description: Answer coach questions and prepare workout, template and sprint changes using the workout_read tool and validated proposals.
---

# Coach actions

Choose the smallest operation that answers the current request. A factual answer
or clarification can have empty proposals. Keep ordinary answers concise.

## Read only the needed context

Use IDs from job.context. Read the exact entity when editing it, retaining its
current revision. Reuse records already read this turn. Fetch overview when the
question needs current progress, readiness, the next workout or scheduling consent.
Page a relevant entity kind when an ID is missing. Fetch more history when the
question calls for it or the evidence conflicts. Avoid a full catalog/history
tour for an isolated edit. Automatic reminders with sufficient supplied context
can be written directly.

## Return changes

Return complete entity data in data_json with its existing base_revision. Preserve
unrelated fields, dates, source metadata and set IDs. An answer describes a
proposal until the athlete applies it. Never claim it was saved.

- Change a logged set or exercise. Read that workout, edit its sets, preserve
  untouched sets and workout metadata, and propose the workout.
- Change the plan. Edit the template's exercises and full set_plan. A one-off
  session correction belongs in the workout.
- Add a missing exercise. Look for a matching exercise first. Propose a new
  exercise before its referencing template, and the template before its sprint.
- Schedule a workout. Read scheduling consent and the sprint. Each scheduled
  entry uses id, date, starts_at and template_id, with optional notes.
  Use date as YYYY-MM-DD, and starts_at as an offset-bearing timestamp on that
  same local date. Example
  {"id":"slot1","date":"2026-01-05","starts_at":"2026-01-05T18:00:00+01:00","template_id":"push"}
  The timezone belongs to the enclosing training context.
- Build a cyclic sprint. Use cycle, start, end and target_sessions. Keep
  scheduled empty unless the athlete opted in and requested dated workouts.
- Analyse photos. Use only the approved photo IDs in this job. Check relevant
  prior estimates and capture dates. Prior photo approval does not carry forward.

## Finish efficiently

Use the supplied schemas as the field reference. After compaction, recover only
the needed schema with workout_read view schema and kind. Check required fields and
cross-references before returning the proposal batch. Return one useful answer,
the changes requested, and a compact narrative update. Ask a targeted question
when a necessary time, exercise or goal is unknown.
