# Native Companion tasks and delivery

The paired Android app owns task history, task details, same-session follow-ups,
notifications, notification replies, calendar reminders and release hints. The
native app connects directly to the relay without another assistant server or app.

The native client/server paths and isolated delivery/recovery tests are
implemented for version 0.7. Firebase Android client configuration, protected
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

## Native delivery

`delivery_mode` defaults to `native`, the only supported mode. Pairing and
`companion_push` credentials are required. A missing active phone raises so
producers retry. Final task states older than one hour expire; active queued or
running tasks retain their latest card. Journal retries collapse unchanged newest
content; state changes and explicit notify-again remain distinct deliveries.
The app receipts after fetching/displaying; blocked channels remain unreceived
until recovered, with bounded backlog behavior. Provider acceptance, receipt and
display remain separate facts.

## FCM errors

Sending failures are reduced to a fixed code and recorded per phone in
`native_push_health`, with the last success time. Response bodies are never kept or
logged, because they can echo registration tokens. `UNREGISTERED` deletes the dead
token row; the phone's next token refresh or re-pairing registers it again, and until
then it only gets events on app open and its periodic sync. Other FCM codes
(`INVALID_ARGUMENT`, `SENDER_ID_MISMATCH`, `PERMISSION_DENIED`, `QUOTA_EXCEEDED`,
`UNAVAILABLE`, ...) keep the registration and the bounded retry. Google token-endpoint
failures carry an `OAUTH_` prefix (`OAUTH_INVALID_GRANT`, `OAUTH_UNREACHABLE`,
`OAUTH_CREDENTIAL`), which separates a bad service account or clock from an FCM
rejection.

## Owner status

`GET /relay/v1/notifications/status` with the submit bearer token, the same
credential as the calendar-reminder status, independently of the laptop. It returns the effective mode, whether FCM credentials are configured, the
non-revoked paired phones (opaque ID, created and last-seen times, whether a push
token is registered and since when, last accepted hint, last receipt, count and
age of unreceived unexpired events, last FCM error code and time), and the same
totals across phones. It contains no task text, names or tokens.

A hint accepted by FCM with no receipt means the phone has not fetched the event.
Opening the app fetches and receipts too, so test push delivery with the app closed.
The last error code is cleared when a later hint is accepted.

## Deployment configuration

Keep the Firebase service-account JSON outside the checkout and OneDrive. The stock
relay container sees only its `/data` volume and the three service tokens, so
place the file in the relay data directory on the server (for example
`/opt/personal-assistant/data/relay/firebase-service-account.json`, owner
`10001:10001`, mode `0600`) and reference it as `/data/firebase-service-account.json`.
It must belong to the Firebase project that the installed Companion build was
configured with, and the FCM HTTP v1 API must be enabled for it.

```json
{
  "enabled": true,
  "delivery_mode": "native",
  "public_url": "https://YOUR_ASSISTANT_HOST",
  "visibility": "private",
  "companion_push": {
    "project_id": "YOUR_FIREBASE_PROJECT_ID",
    "service_account_file": "/data/firebase-service-account.json"
  }
}
```

Android builds receive the Firebase project/app metadata
as build configuration and include the Firebase Messaging runtime. This public SDK
metadata is distinct from the private service account, pairing credential and voice
API key. No secret, device token, personal hostname or identity belongs in public
source. A clone can deploy its own server and Firebase project.

### Preflight

`python -m personal_assistant.relay.preflight` runs in the relay image against the
real `/data/notifications.json`. `scripts/deploy_server.sh` runs it with
`docker compose run --rm --no-deps` after building the image and before `up -d`, so
a bad file fails the deploy while the running relay stays up instead of crash-looping
tasks, groceries and voice. It checks the mode and its requirements, the public URL, loads the service account, performs the OAuth token
exchange and sends an FCM `validate_only` dry run to a topic. Nothing is delivered
and no secret is printed. Credential, project and permission rejections fail. Google
being unreachable, unavailable or rate limiting the token exchange, and any other
dry-run outcome, only warn, so a Firebase-side change or outage cannot block a
deploy. A config-only edit is not covered by the
deploy script, so run the same command by hand before restarting:

```sh
cd infra/server
docker compose --env-file /opt/personal-assistant/.env run --rm --no-deps -T relay python -m personal_assistant.relay.preflight
```

## Existing deployment migration

Follow [retirement and recovery](retire-home-assistant.md) before removing legacy
services. Verify the actual paired handset receives and opens native task details;
provider acceptance and emulator proof alone do not establish handset delivery.
