---
name: local-calendar
description: Manage appointments, agendas, cancellations, and reminders in this repository's assistant-owned calendar when the user asks about their schedule.
---

Read `docs/calendar.md` relative to the repository root for command arguments and
reminder semantics. Use the root `assistant_calendar.py` entry point with this
workspace's Python environment, or the installed `assistant-calendar` command.

Query the actual store before answering agenda questions. The default store is
`state/calendar.sqlite3` in this checkout, unless `ASSISTANT_STATE_DIR` overrides
it. Gmail and Microsoft calendars are information sources, not the primary store.

Resolve relative dates at the time of the user's request. Ask when the appointment
time, end, or daylight-saving offset is ambiguous. Do not create events from
examples or uncertain extracted commitments without an agreed ingestion rule.

For source ingestion use stable account-qualified source keys. A conflicting
duplicate needs an explicit update, not a new key. Local cancellation changes
the assistant store; it does not cancel an external booking or contact anyone.

Reminder records are pending work, not delivered notifications. Acknowledge one
only after confirmed transport success. Consult current implementation status
before promising a phone notification. The supervised cloud projection/delivery
service is implemented; see `docs/calendar-reminders.md` for sync and offline limits.

Tests and demonstrations use `--db` with a temporary file. Keep all real entries
and audit records in ignored private state.
