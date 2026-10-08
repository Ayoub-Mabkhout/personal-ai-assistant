# Phone task status

## Find earlier tasks

In Assistant Companion, open **Activity → Task history**. The paired app lists
tasks across both queues with search, timestamps and pagination. Open a task to
read its answers or continue the recorded worker session. Cached details and
unsent follow-up drafts remain available offline. Task notification Details and
Reply use this native conversation. See [native delivery and setup](native-companion.md).

Native task screens and the event journal are implemented. Firebase client/server
configuration, phone registration and actual Details/Reply notification delivery
are separate acceptance steps. Provider acceptance does not establish handset
receipt.

## Legacy browser history and Home Assistant delivery

Open the cloud `/tasks/` page and sign in with the existing Home Assistant account.
It lists tasks across both queues, newest conversations first, with search across
requests and answers and **Load more** pagination. Agent continuation turns stay
grouped under their original task. Open a row for Details and **Continue this task**.
Every task page links back to **Task history**; bookmark the history page for phone
access independent of notifications. A single task's signed link does not grant
access to the full history, so history may require one separate sign-in.

The cloud relay owns phone updates for both queues. It records a notification
revision in the same SQLite transaction as submitting, claiming, requeuing,
finishing, cancelling or expiring a job. The cloud delivery loop calls the selected
Home Assistant Companion notification action, independent of laptop availability.
The Home Assistant acknowledgement includes the short task ID and tells the user
when phone updates are enabled.

One tagged notification per task is updated from queued to in progress and then
completed, failed or needs input. Active cards persist; final cards are dismissible.
Progress updates alert once; terminal results can alert again. Queued cards report
unavailable or blocked laptop state; a running card reports lost connection before
its execution lease expires. No heartbeat notification spam is sent.

Failed delivery retries with persistent bounded backoff. A new task state resets
the retry delay and supersedes an older pending state. Acceptance acknowledgements
are revision-fenced, so a delayed queued push cannot mark a later completion sent.
Restarting the relay preserves pending delivery. Repeating a submission does not
create another notification. Rapid transitions can collapse to the current state;
Pushes use a positive 24-hour lifetime to permit delivery after temporary phone
disconnection; they are not discarded immediately merely because the handset is
offline. The Details page always fetches authoritative current task state.
The Assist reply still confirms initial server acceptance. Historical completed
tasks are not backfilled when enabling the feature.

The Details button opens `/tasks/agent/TASK_ID?view=TASK_TOKEN` or its command-queue
equivalent. The signed link opens that exact task without a Home Assistant
sign-in, even in a fresh browser tab. It displays the request, current status,
result and state history. The token is removed from the visible URL after loading
and retained for that task in browser storage. It exposes no
CLI traces, credentials or worker prompts. Summaries may reference files; the view
does not grant access to the laptop filesystem. The link cannot authorize another
task, queue changes or Home Assistant administration. It remains valid across
relay restarts; rotating the protected `/data/task-links.key` invalidates old links.
Do not copy that key or signed-link QA credentials into OneDrive or source control.
Anyone intentionally given an agent task link can read its conversation and submit
follow-up instructions to it through the task page. The page issues a separate
task-scoped continuation capability; raw queue administration remains unavailable.
See [task-page continuations](notification-replies.md#continue-from-task-details).

Older unsigned links still support Home Assistant sign-in. That login now persists
across browser tabs, and its OAuth return URL carries the original task explicitly
instead of relying on a URL fragment or a tab-only storage entry. There is no
browser task-result offline cache. The native app has its own task cache. This is
a personal Home Assistant instance: valid logged-in users can view task details,
as with the existing groceries app. Do not add unrelated users without introducing
an owner-only authorization policy for personal tasks.

Runtime configuration is `/data/notifications.json`; see the disabled public
shape in `config/task-notifications.example.json`. The HA refresh credential file
must remain in protected cloud storage, mode 0600, readable by relay UID 10001.
Never add its contents to source, command arguments, or OneDrive. Existing laptop
notifications remain disabled to avoid duplicate terminal pushes.

Home Assistant API acceptance is recorded as `phone_notification_accepted` in task
history. It is not proof that Android displayed the message: push transport,
notification permissions and handset connectivity still apply. Device receipt
requires user confirmation. The live cloud acceptance test covers queued, running
and completed; unit tests cover failure, needs input, cancellation, expiry,
disconnection, retry and stale acknowledgements.

The owner can refresh a notification via POST
`/v1/agent/prompts/TASK_ID/notify` (or `/v1/commands/TASK_ID/notify`). This queues a
notification update without changing the task's state, result, attempts or execution.

[Companion notification fields](https://companion.home-assistant.io/docs/notifications/notifications-basic/).
