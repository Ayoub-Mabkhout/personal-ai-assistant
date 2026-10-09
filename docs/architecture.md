# Implementation architecture

Native Android Companion, an HTTPS cloud relay with durable SQLite stores and an
outbound laptop worker form the assistant. The laptop owns the local calendar,
private source connectors and headless agent execution. A persistent Luna
dispatcher selects models/effort. The relay owns grocery/recipe data, queues,
conversations, pairing, reminder projection and phone event journals.

Caddy terminates TLS and proxies only to the relay. Standalone owner password
login uses salted scrypt hashes and revocable HttpOnly web sessions. Headless
clients use protected submit-token references; workers use distinct credentials.
Phone pairing remains revocable and independent of web login. The phone works
over mobile data or Wi-Fi without a shared LAN or always-on VPN.

Home Assistant integrations and the legacy speech stack have been retired.
Native Companion preserves its local Hey Chat detector, rolling capture buffer,
durable offline queues, task cache, Android TTS and supported Clock handoff.
Configured cloud voice transcription and explicit conversation bridges use the
protected provider configuration; missing configuration fails clearly.

Shopping edits are immediate server transactions without a model or laptop.
Local calendar remains the primary store; a versioned cloud projection schedules
native reminders while the laptop sleeps. Preserve one calendar writer and check
projection and handset delivery separately. See [calendar reminders](calendar-reminders.md).

Phone command IDs exist before upload; relay acknowledges after persistence.
Workers use fenced renewable leases, persist results before acknowledgement,
and reconcile interrupted effects. Stable task/follow-up IDs resume recorded
sessions and prevent duplicate queue actions. Original timestamps/timezones and
expiry rules survive reconnects. Saved locally, queued in cloud and completed
are distinct verified states.

FCM hints contain opaque IDs only. Paired phones fetch protected event content;
provider acceptance, device receipt and displayed cards are separate facts.
Wake accuracy, locked behavior and battery require physical-phone testing.
Android permissions/Clock dispatch cannot prove an alarm was registered.

All owner records and deployment evidence belong in ignored/private protected
storage. Source content is untrusted; no background correspondence, purchases or
financial actions are authorized by this architecture. See [deployment](server-deployment.md),
[native delivery](native-companion.md) and [retirement recovery](retire-home-assistant.md).
