# Phone, relay, and headless integrations

Design researched on 2026-10-01. The selected implementation baseline is in
[architecture.md](architecture.md) and costs are in [costs.md](costs.md).
The cloud stack and outbound laptop calendar worker are deployed. Phone access works through an external
HTTPS URL over mobile data or any Wi-Fi, without sharing the server's LAN.
The existing local calendar remains the primary calendar.

## Architecture

Android voice companion -> durable authenticated cloud relay -> outbound laptop
worker -> local calendar, source connectors, and headless Codex jobs.
Results travel back through the relay and push notifications. The current open
desktop chat is not itself a background service. Jobs use this repository and
private continuity context so conversation memory is not the only durable state.

Codex CLI was verified locally: version 0.159.0, signed in using ChatGPT.
[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
supports scripted jobs with saved authentication, subject to Codex usage limits.
Heartbeats, reconnection, sync bookkeeping, and notifications are ordinary code,
not recurring model prompts. Separate API speech/model services are optional.

## Execution memory recommendation

Use a durable execution journal as authoritative memory. A worker reads relevant
history for each request. A resumable coordinator can plan/delegate complex jobs;
simple jobs need not pay for both a coordinator and a separate worker model turn.
The calendar worker uses a durable ledger today; an explicitly invoked coding
runner captures JSONL events and session IDs. A persistent model coordinator and
general cloud-to-AI dispatch are not enabled. See [coding workbench](coding-workbench.md).

Capture each worker's Codex JSONL events, stderr/exit status, structured result,
and verified business outcomes under private state. Keep request/task/parent IDs,
source references, artifacts, approvals, timestamps, and failure/retry states in
a queryable task ledger. Record progress before and after actions so interrupted
work can be reconciled. A final natural-language summary alone is insufficient.
Source message content is untrusted data; redact authentication data from logs.

If using a coordinator, persist its exact session ID and resume that ID rather
than --last, which could select a child worker's session. Serialize updates to
one coordinator session and explicitly return child results with trace pointers.
Launching a subprocess does not automatically put its full history in the
parent's model context. Keep lightweight ongoing memory notes grounded in the
ledger; fetch detailed traces when needed. Do not load all lifetime history into
every model request. The journal must remain usable if a session is compacted,
lost, replaced, or crashes. Codex exec --json and exec resume are verified in the
local CLI help and documented in the official non-interactive-mode guide.

## Queue and readiness behavior

- Phone saves a UUID-tagged command in a local outbox before attempting upload.
  If offline it says the request is saved on the phone, not on the server.
- Relay persists before acknowledging. Retried UUIDs deduplicate; a reused UUID
  with different content is rejected. Acknowledged upload is not task completion.
- Worker sends readiness heartbeats (four-second polling, 15-second lease renewal, with a
  60-second expiry). Readiness covers the runner, not merely network connectivity.
- Report laptop ready, laptop unavailable, execution blocked, or status unknown.
  An unreachable relay means unknown laptop state. Include last contact time.
- Laptop reconnects automatically with bounded backoff/jitter. Start at Windows
  sign-in and restart after crashes; test sleep/resume and network changes.
- Worker claims one task with a renewable lease. Recover abandoned leases; stale
  workers cannot acknowledge newer leases. Store local progress/results before
  remote acknowledgement so redelivery does not repeat completed actions.
- Requests retain original creation time, timezone, transcript, and optional
  deadline. Resolve relative dates when spoken, not when the laptop wakes up.
  Re-evaluate stale commands; never blindly execute an expired instruction.
- Expose queued, running, needs input, completed, failed, cancelled, and expired
  states. Allow cancellation. Calendar writes use stable source keys. External
  irreversible actions need action-specific idempotency and the user's direction;
  a transport cannot promise exactly-once effects for every external service.
- Phone uses push for meaningful transitions and queries status on voice
  activation. Persist uploads with Android background work. Immediate background
  delivery cannot be guaranteed when Android defers work or the app is force-stopped.

Hosting, TLS, device pairing, authentication, backups, and queued-data retention
must be configured before deployment. Use outbound laptop connections, without
exposing Windows ports or Codex app-server publicly. Most processing and source
credentials stay on the laptop; queued payloads and private state stay out of Git.

## Voice feasibility

The target is an Android phone; its model belongs in the private profile.
Voice while locked and low battery use require device-specific validation.

[Home Assistant Assist on Android](https://www.home-assistant.io/voice_control/android/)
is an open-source reference for lock-screen/default-assistant and local
microWakeWord support. Its experimental wake-word feature uses more battery than
Google's hardware-assisted path. Measure overnight battery drain and wake
reliability before committing to it. Google-equivalent efficiency is not promised.
A button/gesture invocation is a lower-battery fallback. Stock Home Assistant is
not verified to satisfy the offline queue contract; integration or app changes
are needed. Installing the app alone does not implement this assistant.

A native companion needs a durable outbox, spoken acknowledgements, push results,
and on-device speech recognition where supported. If transcription is unavailable,
save audio locally and clearly say only audio was saved for later transcription.
Test lock-screen permissions, manufacturer background behavior, battery saver, reboot,
and force-stop on the actual phone before asserting support.
References: [speech recognition](https://developer.android.com/reference/android/speech/SpeechRecognizer)
and [persistent work](https://developer.android.com/develop/background-work/background-tasks/persistent).

## Sources

Authentication proposal: source connections live on the laptop, separately from
phone-to-relay device pairing. Pair the phone using a short-lived one-use QR/code
approved on the laptop; use per-device revocable credentials protected by Android
Keystore-backed storage. Keep laptop source token/session material in Windows
protected storage. Relay holds queued requests and status, not inbox passwords.
Pairing setup and device recovery may require unlock; lock-screen routine use is
a separate feature. Public Git contains no credentials or personal event traces.

For autonomous multi-account mail ingestion, prefer dedicated read-only adapters:
Google desktop OAuth with PKCE/local callback and offline refresh, Microsoft
delegated OAuth with offline_access and read scopes, one connection per account.
User signs in through the provider browser and completes required MFA/consent.
Adapters refresh access tokens while permitted; revocation or organizational
policy can require human reauthentication. Report needs-sign-in separately from
laptop-offline. App registrations and OAuth consent are not configured yet.
Interactive plugin connections are useful for initial exploration but must not
be assumed to provision credential storage for a standalone ingestion worker.

WhatsApp bridge pairing uses the linked-device flow (QR/code), retaining its
device session on the laptop. It is an unofficial integration to evaluate,
not a guaranteed permanent session. Messenger/Instagram full-personal-account
bridge compatibility/authentication remain unverified. Android notification
capture uses user-granted notification access rather than social passwords and
has the partial coverage described below. Mattermost needs the server address
and permitted channels plus server-supported OAuth/token authorization.

| Source | Headless route | Conditions |
| --- | --- | --- |
| Gmail | Prepared read-only OAuth API collector | User consent pending; resumable full scan, incremental history planned |
| Outlook mail/calendars | Plugins initially; delegated Microsoft Graph per account if needed | Mail.Read for bodies; appropriate calendar-read scope; organizational consent may be required |
| Mattermost | Official REST API, optionally websocket events | Authorized server/token and allowed channels; reconnect backfill |
| WhatsApp | Evaluate unofficial linked-device whatsmeow, or notification intake first | Headless receiving supported by project; pairing/history coverage and session reliability need tests |
| Personal Messenger/Instagram | Scoped Android notification listener initially | Some incoming notification text; not full history, outgoing messages, or guaranteed media |

Gmail, Outlook Email, and Outlook Calendar plugins were found uninstalled and
suggested for connection. No source access has occurred. Search did not return
a matching Mattermost/personal-chat plugin; it is not an exhaustive directory.
Plugin sign-in does not expose OAuth credentials to arbitrary scripts. Verify
runner plugin support or provision separate OAuth connections for the worker.
No passwords or refresh tokens should be pasted into chat.

Meta official messaging integrations target Page/professional account contexts;
personal-account conversation access is not established. Android notification
intake requires user permission, a source allowlist, and careful deduplication.
Source message contents are data, not instructions to the assistant. No automatic
replies or reading-state changes are included in initial ingestion.

References: [Gmail sync](https://developers.google.com/workspace/gmail/api/guides/sync),
[Gmail offline access](https://developers.google.com/workspace/gmail/api/auth/web-server),
[Graph delta](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0),
[Mattermost API](https://docs.mattermost.com/api),
[whatsmeow](https://github.com/tulir/whatsmeow), and
[notification listener](https://developer.android.com/reference/android/service/notification/NotificationListenerService).

## Build sequence

1. Relay/worker with typed input: sleep laptop, verify unavailable state, retain
   command, wake laptop, reconnect, create exactly one calendar entry.
2. Phone capture/outbox, speech/TTS, push, and lock-screen/battery device tests.
3. One personal inbox; checkpointed intake, provenance and deduplication; then
   additional inboxes and source calendars.
4. Mattermost and scoped social intake; test a fuller WhatsApp bridge if needed.

Acceptance checks include duplicate uploads, crashes after local action but
before relay ack, stale leases, expired deadlines, revoked source tokens, Codex
usage exhaustion, blocked permissions, reboots, and relay/network failure.
