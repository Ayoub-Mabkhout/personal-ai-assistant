# Assistant-managed calendar

The calendar belongs to this assistant workspace. Gmail, Outlook, and other
calendars can become sources; none owns the primary calendar. Interact through
the assistant in chat. A calendar dashboard is not required.

`assistant_calendar.py` provides a local SQLite store and JSON commands the
assistant can execute. The runtime database defaults to `state/calendar.sqlite3`,
resolved relative to the workspace, and is ignored by Git. The process variable
`ASSISTANT_STATE_DIR` can relocate runtime state outside the checkout. Code lives
in `src/personal_assistant/calendar.py`; the root command remains compatible.
There is no external
account, server, model API charge, or network request in these commands.

## Setup

Python 3.10 or newer is required. From the project directory on Windows:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe assistant_calendar.py init --timezone Europe/Berlin
```

The timezone is local configuration, not tied to an account. `init` is safe to
repeat with the same timezone and refuses to silently replace an existing one.
Windows needs the first-party `tzdata` package for IANA timezone data.
See [Python timezone documentation](https://docs.python.org/3/library/zoneinfo.html).
SQLite is included in Python; see [SQLite interface documentation](https://docs.python.org/3/library/sqlite3.html).

## Assistant workflow

Use the calendar as the source of truth for calendar requests; query it before
answering rather than relying on chat memory. Resolve relative dates using the
user's current local date/time. Ask for missing or ambiguous appointment details
when needed. Do not infer a real appointment from examples or test data.

- Add a confirmed appointment with its source reference when available.
- Use a stable source key such as `connector:account:message-id:commitment-id`
  for ingested commitments. Repeated identical imports return the existing event;
  conflicting changes require an explicit update. Include account identity so
  IDs from different inboxes do not collide.
- Query the agenda for daily/weekly briefings and scheduling questions. Agenda
  ranges include overlapping multi-day events; the upper boundary is exclusive.
- Update or cancel on the user's direction. Calendar cancellation changes the
  local entry only; it does not contact an organizer or cancel an external booking.
- Add reminder lead times based on the user's instructions. There is no automatic
  reminder schedule until preferences are chosen. Zero minutes means at event start.
- Keep uncertain extracted commitments as proposals in chat until calendar
  ingestion rules have been agreed. External accounts are not connected yet.

Commands below are developer/assistant examples, not instructions the user must
run. Replace example data with the actual request. All output is JSON, including
runtime errors (nonzero exit status). Pass `--db PATH` before the subcommand for
isolated tests or another store.

```powershell
.venv/Scripts/python.exe assistant_calendar.py add --title 'Example appointment' --start '2030-01-15T10:00' --end '2030-01-15T11:00' --remind-minutes 60 --source-key 'example:appointment:1'
.venv/Scripts/python.exe assistant_calendar.py add --title 'Example day' --start '2030-01-16' --all-day
.venv/Scripts/python.exe assistant_calendar.py agenda --from '2030-01-15' --to '2030-01-22'
.venv/Scripts/python.exe assistant_calendar.py get EVENT_ID
.venv/Scripts/python.exe assistant_calendar.py update EVENT_ID --start '2030-01-17T10:00' --end '2030-01-17T11:00'
.venv/Scripts/python.exe assistant_calendar.py update EVENT_ID --clear-reminders
.venv/Scripts/python.exe assistant_calendar.py cancel EVENT_ID
.venv/Scripts/python.exe assistant_calendar.py history EVENT_ID
```

Timed entries require an explicit end time. All-day entries use date values and
an exclusive end date (omitting the end creates one local calendar day). Times
without offsets use the event's timezone or the configured default. Nonexistent
daylight-saving times are rejected; repeated local times need an explicit offset.
Events persist both their local timezone/dates and their UTC instants.

## Reminder delivery boundary

`due` returns pending reminders for active, unexpired events. Reading it never
marks anything delivered. Repeated calls therefore retain notifications until
delivery succeeds. Updates that move an appointment invalidate the old reminder
IDs and create replacements; cancellation removes pending reminders. Title-only
edits retain delivery history. Expired events are excluded after offline periods.

```powershell
.venv/Scripts/python.exe assistant_calendar.py due
.venv/Scripts/python.exe assistant_calendar.py ack-reminder REMINDER_ID
```

`ack-reminder` records transport acceptance, not proof the user read a notification.
The cloud reminder projection and notification pump are implemented in
`src/personal_assistant/relay/reminders.py`. Once enabled alongside the cloud HA
notification sender, reminders already synced to the server run while this laptop
is asleep. See [cloud reminder delivery](calendar-reminders.md) for setup and limits.
No default lead times are added; appointments need explicit reminder settings.

## Current limits and verification

This first version handles one-off timed and all-day entries. Recurring series,
external calendar sync, invitations and calendar UI are not implemented. Cloud
phone reminder code is implemented; private runtime status records whether it is
enabled and synced. Do not create appointments from examples or uncertain sources.

Tests use temporary databases and cover daylight-saving boundaries, overlapping
events, persistence, concurrent duplicate ingestion, moving/cancelling reminders,
delivery acknowledgement, expired events, validation rollback, and CLI behavior:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_calendar.py -v
```
