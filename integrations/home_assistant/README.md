# Home Assistant integration

YAML configuration and custom English sentences route assistant requests into
the relay and query laptop readiness. Native shopping-list actions run on the
server without an AI worker. The cloud relay can deliver Companion phone updates
for queued, running and terminal task states; see
[phone task status](../../docs/phone-task-status.md). Use an external HTTPS URL;
shared LAN is unnecessary. Private continuity records actual deployed service state.
See [deployment](../../docs/server-deployment.md) and [architecture](../../docs/architecture.md).

The `assistant_dispatch` custom conversation entity is the Personal assistant
pipeline's default agent. It tries native programmed intents first; only
`no_intent_match` falls back to the Luna queue, using the original text and a
stable HA context-derived request ID. Other native errors do not trigger another
action. No dispatch keyword is required. Speech engines and task push remain
unchanged. This is server-side routing; it does not make HA available without
an internet connection. Native phone-local behavior is separate.
