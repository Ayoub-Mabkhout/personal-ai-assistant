# Phone scripting through Termux

Companion receives authenticated cloud commands, launches Termux's official
`RUN_COMMAND` service in background mode, and returns stdout, stderr and exit
status. This is a shared CLI/HTTP capability for Claude, Codex or another personal
coding agent. It does not run a model or depend on Codex session tools.

## One-time phone setup

1. Update Companion, then open Settings → Phone scripting.
2. Install Termux from the linked F-Droid page and open it once. Install Termux:API
   from the same source if needed; inside Termux install its commands with
   `pkg install termux-api`. Python can be installed with `pkg install python`.
3. Use Copy Termux setup command, paste/run it in Termux. This enables
   `allow-external-apps=true` without replacing existing settings.
4. Tap Grant command permission and allow Companion to run commands in Termux.
   If Android shows no permission dialog, check Companion's App info → Permissions
   → Additional permissions after Termux is installed.
5. Enable phone commands and run Test connection. Reopen the panel to read the
   actual returned output. If background starts fail, open Termux and exempt it
   from Samsung battery sleeping/optimization; then test while locked.

No root, Accessibility service or ADB is included. Termux retains ordinary Android
app permissions and cannot bypass a locked screen or read other apps' private
storage. A successful emulator/build check is separate from locked Samsung
execution and battery reliability.

## Shared laptop commands

Use the repository Python environment and `scripts/phone_actions.py`; its default
config references protected owner authentication, so no keys need copying into
either agent's prompt. Run from the same personal workspace as the assistant.

```text
python scripts/phone_actions.py termux-capabilities
python scripts/phone_actions.py termux --id task-example-01 --script "uname -a" --label "Phone system" --timeout 30
python scripts/phone_actions.py termux --id task-example-02 --script-file my-phone-task.sh
python scripts/phone_actions.py termux-status task-example-01
```

Scripts execute via Termux `timeout -k 5 SECONDS bash -lc SCRIPT`, with separate
argv fields, a default home working directory and no Windows shell interpolation.
Default command expiry is one hour (`--ttl`, at most one day); execution timeout
is 5–300 seconds. Keep larger files/output on the phone and fetch explicitly;
result text is limited to 32,000 characters per stream and marks truncation.

## Delivery and recovery

The SQLite cloud queue is separate from the laptop-agent queue. Native FCM sends
an opaque event hint; Companion then fetches commands with its pairing token.
Entry-time sync and Android recovery jobs repair missed hints. Recovery checks
are not instant push, and native FCM registration/provider configuration is needed
for prompt background delivery. Existing task-notification delivery mode is not
changed by this feature.

Stable request IDs prevent duplicate submissions. Phone-scoped execution claims
and a local ledger are saved before launch, so a lost result never automatically
reruns a script. Results persist before upload and retry across outages. A missing
callback becomes `uncertain`, not success. A late real callback can resolve it.
Commands already running on the server but lacking the phone's local ledger are
never replayed after application data loss. Disabling commands prevents new
launches; it does not cancel already running processes or discard their results.

Public API prefix: `/groceries/v1/mobile/termux`.

| Endpoint | Authentication | Purpose |
|---|---|---|
| `POST /commands` | Existing owner authentication | Submit id/phone/script/workdir/label/timeout/ttl |
| `GET /commands/{id}` | Owner | Read saved execution state and result |
| `GET /capabilities` | Owner | Read phones' reported readiness |
| `POST /capabilities` | Paired phone | Report installed/permission/enabled |
| `GET /pending` | Paired phone | Fetch only this phone's commands |
| `POST /commands/{id}/claim` | Paired phone | Bind an at-most-once execution claim |
| `POST /commands/{id}/result` | Paired phone | Save result bound to that claim |

References: [Termux RUN_COMMAND](https://github.com/termux/termux-app/wiki/RUN_COMMAND-Intent)
and [Termux:API](https://github.com/termux/termux-api).
