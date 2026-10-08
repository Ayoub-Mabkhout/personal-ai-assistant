# Laptop services

The outbound worker and localhost dashboard run under one per-user supervisor.
On Windows, `scripts/install_assistant_startup.ps1` installs the hidden
`PersonalAssistantServices` scheduled task at sign-in. It runs without elevation,
allows battery operation, restarts failures, and has no execution time limit.
Windows Job Objects tie child lifetime to the supervisor, including forced stops.

The worker polls every four seconds, reconnects with bounded jitter/backoff,
maintains readiness heartbeats, and uses renewable fenced leases. Its private
SQLite ledger stores the request and outcome before acknowledging the relay.
Lost acknowledgements are retried with the same lease; completed read-only work
is not repeated. Cancellation prevents a stale result from being acknowledged.
Relative dates use the original request timestamp and timezone.

Current execution capability is **calendar.agenda only**: today, tomorrow, this
week, next week, or an ISO date. Other requests return needs_input. Calendar writes,
general AI jobs, scheduled reminders, and email scans are not enabled through the
cloud worker. The coding runner is a separate explicitly invoked helper.

## Configuration

Use `config/worker.example.json` as a shape, replacing paths with absolute paths.
Keep the actual configuration, service tokens, HA refresh token, execution database,
locks, and logs in a current-user protected directory outside OneDrive.
Token files contain only their token. The HA auth file contains `refresh_token`
and `client_id`; it does not need the owner's password. An owner token remains
owner-scoped and revocable; it is not a dedicated restricted service account.

Install the package with server extras and verify the real calendar path before
starting. Never initialize a second live calendar as part of worker setup.

```powershell
./scripts/install_assistant_startup.ps1 -Config "$env:USERPROFILE/.personal-assistant/worker/config.json"
Get-ScheduledTask -TaskName PersonalAssistantServices
Stop-ScheduledTask -TaskName PersonalAssistantServices
Start-ScheduledTask -TaskName PersonalAssistantServices
./scripts/restart_assistant_services.ps1
```

The task runs while the user is signed in and the laptop is awake. It cannot
execute while asleep or logged out. The cloud queue retains uploaded commands;
relay readiness expires after 60 seconds. Real sleep/resume and changing networks
still require device tests. Pause via the dashboard creates `pause.flag`; it stops
new claims and reports blocked readiness without discarding requests.

## Results and notifications

Results remain in the relay and local ledger. Optional notifications use HA
persistent notifications and one configured `mobile_app_...` service. Failed
notification attempts remain in a durable outbox with backoff up to one hour;
stable notification IDs/tags replace repeats. HA API acceptance is not proof of
phone delivery. Notification delivery is disabled in the initial local setup.
Enable it deliberately after selecting the phone and checking lock-screen privacy.

Worker logs rotate; supervisor child output retains one previous log at restart
when it exceeds 1 MiB. Runtime traces may contain private task content. The
supervisor diagnostic file records startup failures. Back up these records through
an encrypted/private backup workflow rather than adding them to Git.

## Local dashboard

Open `http://127.0.0.1:8787/`. It serves the profile, calendar, shopping list,
execution history, document catalog, and workbench inventory. Shopping checkboxes
update the actual HA list. Request submission preserves a UUID and original time
in the browser until server receipt is confirmed; retrying uses the same ID.

It binds only to localhost, checks Host/origin, requires a local session token for
APIs, and serves no external assets. Personal data is loaded from private files at
runtime. This dashboard is not published on the HA phone URL. Browser persistence
does not implement an Android offline voice outbox.
