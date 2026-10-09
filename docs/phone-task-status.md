# Phone task status and history

Native Companion fetches task history/details with its paired credential and
opens native conversations from notification events. Stable-ID follow-ups resume
the recorded worker session. Cloud status cards continue while the laptop is
offline and distinguish queued, running, failed, completed and needs-input states.

Browser `/tasks/` supports standalone owner login through a Secure HttpOnly cookie.
A signed task view link remains restricted to its original task; a separate scoped
follow-up token authorizes its continuation. Neither grants owner administration,
other tasks or queue mutations. Owner bearer clients use protected submit tokens.
Browser logout revokes its server session without changing phone pairing.

Notifications use native delivery only. See [native delivery](native-companion.md)
for registration, bounded retries, opaque FCM hints and receipt/display evidence.
