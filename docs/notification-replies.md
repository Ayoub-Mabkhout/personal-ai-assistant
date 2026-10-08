# Replying to task notifications

The selected native Companion opens Details in its task conversation and sends
Reply through the same stable-ID continuation endpoint. It resumes the recorded
worker session, preserves offline drafts and retries the original follow-up ID.
See [native tasks and delivery](native-companion.md) for its pairing and Firebase
requirements. Actual registered-phone notification/Reply delivery still requires
handset acceptance.

## Legacy Home Assistant notification reply path

Task cards contain **Details** and **Reply**. Reply opens the Companion text input.
The text becomes a new prompt in the existing agent FIFO, processed by the same
persistent Luna session. It can provide missing information or ask a follow-up.
The parent task stays unchanged, including `needs_input`, cancelled and failed
states: a reply does not blindly rerun its previous side effects. Follow-ups also
work on calendar-query cards; they enter the agent queue.

The relay snapshots the parent request, state and visible summary, root request
and recent ancestry into `payload.reply_context`. The worker passes it separately
as `followup_context` to the dispatcher. These quoted messages/results are
historical context, not new instructions; `user_request` is the actual current
reply. No raw traces or auth files enter this envelope. Replies remain queued
while the laptop sleeps and receive the normal status/answer notifications.

## Server integration

After constructing the existing submit authorization dependency in `relay/api.py`:

```python
from .replies import reply_router
app.include_router(reply_router({'command': queue, 'agent': agent_queue}, submit))
```

The `/v1/notification-replies` endpoint accepts only the server-side submit
credential. Task-page follow-ups use a different, conversation-scoped capability
and continuation endpoint; they cannot use this administrative reply endpoint.
`integrations/home_assistant/task_replies.package.yaml` forwards only explicit
`mobile_app_notification_action` events with the task action prefix. Its
`relay_authorization` refers to the existing protected HA secret. Install as a
package or merge its `rest_command` and automation sections into the existing
configuration without replacing unrelated settings. No WhatsApp messages or
other received messages trigger this workflow.

Each forwarded envelope contains the original HA event context ID, exact action,
notification tag, reply text and event timestamp. The action/tag must identify
the same existing task. A receipt is saved before queue submission in protected
`notification-replies.sqlite3` beside the agent queue. Its deterministic child
ID and immutable saved payload make HTTP retries and process restarts idempotent,
including a crash after queue submission but before the HTTP response. Relay
startup recovers receipts saved before or after the queue transaction. A reused
event ID with changed content is rejected. A genuinely new reply event is a new
instruction even if its text repeats an earlier one. Event timestamps allow
delayed delivery; future events more than five minutes ahead are rejected.

The HA automation retries the same event three times after connection errors,
then records an HA persistent notification if it cannot save the reply. HA event
delivery itself is not a durable phone outbox; replies issued while the phone has
no connection may require resending. This does not promise exactly-once external
side effects. Existing queue acknowledgements and worker reconciliation apply.

Code tests cover authorization, scoped card identity, preserved parent state,
context, FIFO queueing, duplicate/conflicting events, receipt restart and both
crash boundaries. Handset Reply rendering and end-to-end submission require an
actual phone check after deployment; API acceptance alone does not establish it.

[Companion actionable notification fields and reply events](https://companion.home-assistant.io/docs/notifications/actionable-notifications/).

## Continue from task details

Completed agent pages provide **Continue this task**. The new instruction is saved
in a durable cloud turn inbox and resumes the task's existing headless worker,
using its recorded model, effort, workspace and skill context. It bypasses Luna's
dispatch decision. If the original task only used Luna, that recorded session is
resumed directly. With several workers, the latest recorded worker is continued.
Missing sessions produce an explicit error; a replacement agent is not started.

The original request/result remains intact. Each instruction has its own immutable
receipt, trace and status; the original page shows all follow-up turns. Instructions
wait while the laptop sleeps or another turn runs. Browser retries reuse the same
ID, including a lost acknowledgement or page reload. An unsent instruction is
retained on the phone and retried when the page is opened or reconnects; a closed
browser cannot guarantee background delivery. Notification Details returns to the
original conversation.

`POST /tasks/v1/agent/{id}/followups` accepts `{id, instruction}`. The authenticated
page issues a distinct `X-Task-Followup` capability bound to that task/conversation.
Existing signed notification pages can obtain it without another sign-in. Such
links therefore now authorize viewing and sending follow-ups to their own task;
they cannot select a session, change queue administration or target unrelated tasks.
