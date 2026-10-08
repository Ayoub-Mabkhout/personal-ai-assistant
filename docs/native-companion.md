# Native Companion tasks and delivery

The paired Android app owns task history, task details, same-session follow-ups,
notifications, notification replies, calendar reminders and release hints. The
Home Assistant app is unnecessary once a build with native push is installed and
registered. An old installation can receive its final upgrade hint through the
existing Home Assistant channel; this is a migration step, not a permanent
dependency. Home Assistant's server and legacy browser pages remain available.

The native client/server paths and isolated delivery/recovery tests are
implemented for version 0.6. Firebase Android client configuration, protected
server credentials, phone registration and actual notification receipt/Reply are
deployment and handset acceptance steps. An APK build or fake-provider test does
not establish that this channel is configured or working on a phone.

## Owner pairing and task access

The one-use pairing exchange supplies a revocable `pa_mobile_` credential stored
in Android's private application storage. Only an owner can issue a pairing code.
Pairing authorizes this owner's personal task conversations. The mobile APIs
return requests, answers, timestamps and status, without exposing worker session
identifiers, internal traces, service credentials or queue administration.

The native task client uses:

- `GET /groceries/v1/mobile/tasks?q=...&cursor=...`
- `GET /groceries/v1/mobile/tasks/{agent|command}/{id}`
- `POST /groceries/v1/mobile/tasks/agent/{id}/followups`

A follow-up receives a stable ID on the phone before attempting network access.
The server's existing continuation ledger binds it to the original conversation;
the worker resumes the recorded headless session. Lost acknowledgements and
restarts retry the original ID. They neither redispatch the original request nor
select a replacement worker session. Cached history/details and unsent follow-up
drafts remain usable offline. The native notification Reply action uses this same
continuation path.

## Delivery and recovery

FCM sends a high-priority data hint containing only an opaque event ID. The phone
uses its pairing credential to fetch a durable, phone-scoped event journal over
HTTPS. Task text and answers are never included in the FCM hint. A cursor receipt
is separate from provider acceptance, so a successful send does not claim handset
delivery. Registration-token changes re-register the device and replay unreceived
hints. Revoked phones receive no new hints and cannot fetch events.

Tagged Android notifications update in place as requests move from queued to
running to completed, failed, or needing input. Tapping Details opens the native
task conversation without a browser login. Calendar reminders have a Snooze 10
min action backed by a durable cloud schedule; the laptop can remain asleep. Phone
alarm notifications open the app's existing Android Clock handoff. Clock intent
delegation is still distinct from verified registration in the Clock application.
Release events trigger an authenticated app feed check/download, preserving
Android's installation approval requirement.

Event TTLs and retries are bounded. Recovery jobs and entry-time fetches repair
missed hints; these periodic jobs are not described as push. An authenticated
WebSocket event stream is also available for foreground clients. No wake listener
or always-on application socket is required for FCM notification delivery.

## Deployment configuration

Keep Firebase service-account JSON in the server's protected secret store, outside
the checkout. Configure the relay's private notifications file with:

```json
{
  "enabled": true,
  "provider": "companion",
  "public_url": "https://assistant.example.com",
  "visibility": "private",
  "companion_push": {
    "project_id": "your-firebase-project",
    "service_account_file": "/protected/firebase-service-account.json"
  }
}
```

Android builds receive the Firebase project/app metadata as build configuration
and include the Firebase Messaging runtime. This public SDK metadata is distinct
from the private service account, pairing credential and voice API key. No secret,
device token, personal hostname or identity belongs in public source. A clone can
deploy its own server and Firebase project.

Verify the provider using an isolated paired test device before changing the
notification provider. Verify the actual handset receives and opens native task
details after upgrading; provider acceptance and emulator proof alone do not
establish handset delivery.
