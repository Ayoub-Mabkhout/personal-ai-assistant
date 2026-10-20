# Calendar reminders while the laptop sleeps

The assistant's local calendar remains the primary store. The cloud receives a
complete projection of reminder occurrences, not permission to edit appointments.
After a successful sync, the cloud server can send reminders through its
native Companion provider while the laptop
is asleep. Native delivery uses the phone event journal and configured FCM hints;
Snooze 10 min reschedules durably in the cloud. Firebase setup and actual reminder
receipt/snooze on the handset remain separate acceptance steps.

## Components

- `Calendar.reminder_snapshot()` returns a stable calendar source ID, monotonic
  audit revision and complete set of active reminder occurrences. It does not
  invent lead times, appointments or recurrence rules.
- `scripts/sync_calendar_reminders.py` uses the protected local worker config and
  worker credential. It reconciles accepted receipts into current local reminder
  IDs, then publishes the complete snapshot. `--watch --interval 30` retries every
  30 seconds and should be supervised alongside the laptop worker.
- `ReminderStore` persists the projection, receipts, delivery leases and retries
  in a cloud SQLite database next to the relay queue. Cloud runtime records are
  private. Snapshots contain title, time, location and timezone, but omit event
  descriptions, source URLs and source keys.
- `ReminderPump` shares the relay's configured notification sender. The relay lifespan
  starts/stops it. Its notification visibility follows the configured owner
  preference. It checks due reminders every five seconds.

Service endpoints:

| Endpoint | Credential | Purpose |
| --- | --- | --- |
| `POST /v1/calendar/reminders/snapshot` | Worker | Complete versioned projection |
| `GET /v1/calendar/reminders/receipts` | Worker | Transport-accepted current occurrence IDs |
| `GET /v1/calendar/reminders/status` | Owner | Last sync revision/time and counts |
| `PUT /v1/calendar/agenda` | Worker | Upcoming entries for the phone's Calendar tab |
| `GET /v1/calendar/requests` | Worker | Entries added on the phone, waiting for the laptop |
| `POST /v1/calendar/requests/{id}` | Worker | Whether the laptop added one |
| `GET /groceries/v1/mobile/calendar` | Phone | Agenda, reminder states and its own requests |
| `POST /groceries/v1/mobile/calendar/requests` | Phone | Queue one entry for a day |

These are relay paths. Public deployment mounts them under `/relay` as it does
other queue endpoints. No anonymous calendar read or calendar write endpoint is
provided. A snapshot request needs a larger bounded request allowance than an
individual task prompt. The record count is limited to 5,000 and field lengths
are bounded; the relay's byte limit may reject a particularly large snapshot.

The same sync applies entries queued on the phone first (source key
`companion:<request id>`, so a repeated request is added once), then publishes
the reminder snapshot and the phone agenda. A relay without the calendar feed
still receives reminders. Reminder cards are phrased from when they fire:
"Tomorrow 13:30–14:15" for appointments, "Sam's birthday is in a week" or "is
tomorrow" for birthdays, which carry a cake medallion on the phone.

For an already initialized calendar and configured relay, one-shot sync is:

```powershell
.venv/Scripts/python.exe scripts/sync_calendar_reminders.py
```

For a supervised process:

```powershell
.venv/Scripts/python.exe scripts/sync_calendar_reminders.py --watch --interval 30
```

## Updating, cancelling and recovery

Snapshot replacement removes occurrences absent from the latest local calendar,
including cancelled appointments and reminders regenerated when an event moves.
Title/location/end edits retain occurrence delivery history. An older revision,
a reused occurrence ID with a different due time, or another calendar source ID
is rejected. Repeating an identical snapshot is harmless. A restored older
calendar backup needs deliberate reconciliation rather than silently overwriting
newer cloud state.

Receipts and retry state survive relay restarts. A 30-second delivery lease prevents
two pumps from concurrently sending the same occurrence. Failed transport calls
retry with bounded backoff. After HA accepts a notification it is not resent on
each sync. A crash after HA acceptance but before saving its receipt can repeat
delivery; the stable Android notification tag replaces the same card instead of
creating separate cards. This is not an exactly-once handset delivery guarantee.

Before transport, the pump rechecks that the occurrence is current and unexpired.
Already ended appointments do not generate late catch-up notifications. Push TTL
is bounded by the appointment end and 24 hours. API acceptance does not prove
handset receipt or that the notification was read.

An offline laptop cannot publish a new appointment, move or cancellation. The
cloud acts on its last successful snapshot until the laptop reconnects. Changes
already synced continue to work without the laptop. Already displayed reminder
cards are not recalled when an event is later cancelled. Snooze/dismiss actions,
quiet-hour rules, recurring events and calendar editing from the phone are not
implemented by this projection.

## Verification

Tests use temporary stores and fake senders; they do not create live appointments
or test phone notifications. They cover delivery with the local calendar closed,
restart persistence, cancellation/moves, stale/conflicting snapshots, concurrent
delivery leases, durable retry, expiry, authorization and receipt reconciliation.

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_calendar_reminders.py -v
```
