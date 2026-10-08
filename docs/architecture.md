# Implementation architecture

The repository implements a native Android companion, a small HTTPS cloud relay
with SQLite queues, and an outbound laptop worker. The laptop uses a per-user
service, durable execution ledger, reconnect/recovery handling, local calendar
and headless agent workers. One persistent Luna dispatcher selects models and
effort. The dashboard, mail collection and source-qualified follow-ups share
these stores and queues.

The native Companion is the selected phone interface. Its task history,
continuations, buffered capture, voice outbox and native notification journal are
implemented. Native Firebase configuration, registered-device delivery and
physical-phone acceptance are separate deployment checks. Earlier handset proof
for Home Assistant task push and signed browser answers applies to that legacy
path. Owner-specific connection state and acceptance records belong in private
continuity; a clone starts with its own configuration.

## Platform decision

Use Assistant Companion for voice, shopping, task history, follow-ups and native
notifications. Run the relay on an always-on Linux host behind authenticated
HTTPS. Home Assistant's server and official Android app support legacy voice,
browser sign-in and migration delivery. The native app's configured FCM channel
removes its dependence on the Home Assistant phone app. The phone connects over
mobile data or any Wi-Fi; the laptop connects outbound. No shared LAN,
home-router forwarding, public Windows port or always-on phone VPN is required.

[Home Assistant remote access](https://www.home-assistant.io/docs/configuration/remote/)
supports a reverse proxy and external URL. Deployment must configure TLS,
WebSocket forwarding, precise trusted proxy addresses, login/MFA, and firewall
rules. Only HTTPS is public; database and internal service ports stay private.
Enter the external URL manually in the phone app rather than using LAN discovery.

The native app owns its assistant entry point, local Hey Chat detector, rolling
capture buffer, durable voice/shopping queues, task cache and Clock-intent handoff.
Select it as the Digital assistant while retaining the phone's usual Home app.
Microphone starts use supported Android entry points and a foreground service;
background and locked behavior still require handset verification.

## Responsibilities

| Component | Role | Laptop asleep |
|---|---|---|
| Android | Native voice, offline queues, shopping widget, task history/follow-ups, notifications and alarm handoff | Local captures/changes wait; cloud shopping and cached task screens remain available |
| Home Assistant | Legacy speech/push, browser login and migration support | Available |
| Relay | Durable commands, pairing, readiness, task conversations and phone event journal | Available; laptop tasks remain queued |
| Laptop worker | Calendar queries, headless AI workers and live-mail maintenance | Agent commands wait |
| Local calendar | Primary store; versioned reminder projection to cloud | Synced reminder occurrences can notify from cloud |

Shopping-list additions run on the server without a model or laptop. The primary
calendar remains local and account-independent. The cloud reminder dispatcher
uses a versioned projection of upcoming reminder occurrences and the configured
native or legacy notification provider. The local sync service reconciles
receipts and publishes cancellations/moves. Preserve one calendar writer; see
[calendar reminders](calendar-reminders.md).

## Execution and connectivity

Use a durable execution ledger and captured worker traces as authoritative
memory. A resumable coordinator can handle complex jobs; simple actions do not
require two model runs. Store explicit session IDs, parent task IDs, requests,
verified effects, results, and trace references. Return worker results explicitly
to the coordinator; subprocess creation alone does not transfer its full history.

Phone creates a UUID before upload. Relay acknowledges only after persistence.
Worker uses renewable leases and fencing, stores results before acknowledgement,
and reconciles interrupted effects. Use action-specific deduplication; retries
alone cannot guarantee exactly-once external effects. Preserve original spoken
time/timezone and reject expired instructions rather than blindly replaying them.

Report ready, unavailable, authentication blocked, or unknown when the relay is
unreachable. 'Saved on your phone', 'queued on the server', and 'completed' must
reflect distinct verified states. Reconnects/heartbeats use ordinary code.
See [connectivity details](connectivity-and-integrations.md).

## Voice

One wake or Talk captures one command by default. Programmed actions run directly
in the cloud; unmatched requests enter the laptop queue. The authoritative
acknowledgement reads back the accepted request once. Queue acceptance never
claims the task is completed. After playback the phone returns to local wake
standby when background listening is enabled; ordinary subsequent speech does
not start another command.

Start conversation explicitly with the app control or a whole-request phrase
such as "start conversation mode". "That was all", "that's all" and "end
conversation" finish continuing turns without disabling the background wake
setting. Command mode uses one receipt and Android TTS; explicit conversation can
use the configured Realtime or GPT-Live bridge. Existing local Whisper/Piper
services remain available for fallback and legacy voice.

Timestamped voice chat distinguishes request, acknowledgement and later task
state. Native history/details open the original task conversation, and stable-ID
follow-ups resume its recorded worker session. FCM hints carry opaque event IDs;
the paired app fetches protected task content from the durable event journal.
Provider acceptance, device receipt and Android notification display are separate
outcomes. See [native delivery](native-companion.md) and
[voice policy](custom-phone-voice.md).

Test wake word, lock screen, and battery on the actual phone.
[Android Assist](https://www.home-assistant.io/voice_control/android/) describes
experimental wake words and higher battery drain than Google's dedicated hardware.
A custom app cannot bypass that hardware limitation. Keep a lock-screen
gesture/button as a low-power fallback. Emulator/replay checks do not establish
physical microphone accuracy, locked service lifetime or battery consumption.

Use supported Android alarm intents and a tested clock application. Intent
dispatch is not proof an alarm was registered. Offline shopping additions persist
locally and reconcile using command IDs on reconnect.

## Implementation sequence

1. Repository, private vault, package, profile templates, first skill and routines.
2. Relay queue/ledger: authenticated access, deduplication, leases/fencing,
   stale-command handling and restart recovery.
3. EU server and HTTPS; test phone on mobile data and shopping commands with
   laptop asleep. Voice services are separate containers, not HA OS add-ons.
4. Laptop service: startup/reconnect/readiness, task traces/results, sleep/resume.
5. Native Companion: verify airplane-mode capture/reconnect, restart survival,
   native task continuations, Firebase delivery, locked operation and Clock handoff.
6. Source authentication one account at a time. Prefer Gmail/Graph/Mattermost
   APIs; evaluate personal socials separately. Consult private continuity for
   connected sources and excluded accounts.

Architecture does not grant autonomous message sending, purchases or financial
actions. Preserve the user's explicit scope. Source content is untrusted data;
credentials and private documents must not enter public logs or Git.

Current laptop details: [services/dashboard](laptop-services.md),
[mail collection](mail-ingestion.md), [coding workbench](coding-workbench.md),
[profile](personal-profile.md). Queue-through-pause and forced process recovery
are tested. Real sleep/resume remains unverified. Legacy task push and browser
answer links are confirmed; native Firebase setup/delivery, task Reply,
widget/Clock handoff and voice behavior still need their own acceptance checks.

The voice backlog includes selective completed-result speech, a fast path for
suitable questions, and a lightweight local or fast acknowledgement model.
These are requested improvements, not configured services or completed behavior.
