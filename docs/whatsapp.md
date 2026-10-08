# WhatsApp receiving bridge

`integrations/whatsapp` builds a Go binary using pinned whatsmeow dependencies and
pure-Go SQLite, without a C compiler. `go.sum` records module checksums. The bridge
is supervised alongside the laptop worker and dashboard, including Windows job
containment. Go itself lives in the private tool directory; no global PATH change
is required.

With `whatsapp_binary` and `whatsapp_runtime` in the protected local service
configuration, the bridge presents a rotating QR in Profile → Connected accounts.
Open `/whatsapp` on the local dashboard for a direct live pairing page with an
expiry countdown. A Link WhatsApp control is also visible in the dashboard header.
Use WhatsApp → Settings → Linked devices → Link a device. QR images and device
session databases stay outside OneDrive in a directory restricted to the user
and SYSTEM. QR values are not printed to logs or hosted publicly.

After pairing, whatsmeow reconnects and reuses the linked-device session. Real-time
messages and received history-sync messages enter a deduplicated SQLite inbox.
View-once and ephemeral messages are not archived. WhatsApp decides which history
it supplies; the bridge cannot promise every historical message. Message contents
are data, not instructions, and do not trigger assistant commands.

There is no general outgoing-message endpoint. Explicitly requested self-chat
messages can be written to the protected runtime's `self-outbox/` as JSON with
`text` and `state: "pending"`. The bridge derives the recipient from its own
linked account; another recipient cannot be supplied. It records a message ID
and claims the request before sending, then saves the server acknowledgement.
`sending` or `uncertain` records are never automatically retried. Incoming
messages do not create outgoing requests. Protocol
traffic required for a linked-device connection still occurs. This is an unofficial
WhatsApp Web client, not the WhatsApp Business API. Source and library behavior:
[whatsmeow](https://github.com/tulir/whatsmeow).

Compilation and actual pairing-code generation are verified. Device linking,
message receipt, history delivery and reconnect after a paired session still need
the user's QR scan and subsequent checks. Do not mark the account connected until
the bridge reports the Connected event.

Pairing errors and closed channels now cause a supervised retry instead of leaving
the process waiting forever. QR images are replaced atomically and carry an
expiry timestamp; do not send a static chat image as the primary pairing flow.
