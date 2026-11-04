# Task routing and separate queues

## JEV direct routing

Set `dispatcher_mode` to `jev` in the protected laptop worker configuration to
use one TypeSafe Jev classification call for each new agent task. Code chooses
the account first (`orchestrator/routing_policy.py`, no model call):

1. An explicit request in the user's own words ("use Opus", "route this to
   Codex", "model: gpt-6-astra", "at high effort") is binding. Quoted text,
   comparisons and hypotheticals ("should I use Haiku?") are not requests;
   negations exclude instead. Conflicting or unknown versions are refused.
2. Mail work (a mailbox noun near a mail action) pins Codex, whose Gmail tools
   Claude lacks.
3. Otherwise the account with the better allowance score wins: mostly the
   tighter of its five-hour and weekly headroom, plus a bonus for allowance about
   to reset unused. Exhausted or unusable accounts are skipped; stale or missing
   readings count as modest unknown headroom, never as free capacity.

Jev then sees only that account's profiles, without allowance figures, and picks
the least demanding sufficient model and effort plus a task type. Code supplies
the workspace, original prompt and required skills, launches one fresh worker,
and publishes that worker's answer directly. There is no Luna planning turn or
model review after the worker finishes.

Luna/Haiku are restricted to lightweight work. Sol and Opus are policy peers for
general capability, with Opus preferred for demanding creative work. Astra is
reserved for exceptional reasoning difficulty.
Routing reads cached allowance data without spending a separate model call to
refresh it. Worker calls still record their usual capacity observations.

New tasks do not search recent tasks or infer a session to resume. Explicit task
Replies and follow-ups retain their existing recorded-worker continuation path.
Assistant-development requests can still be forwarded to the interactive sessions
when the coordination bridge is configured. Attachments, required email skills,
task-file delivery, cancellation, queue leases and interrupted-worker recovery
keep the existing contracts.

Configure `jev_api_key_file` as an absolute protected path outside the checkout,
or provide `JEV_API_KEY` / `TYPESAFE_API_KEY` to the service environment. Optional
`jev_model` and `jev_timeout_seconds` configure the classifier. The default model
is `jev-latest`, using `https://api.typesafe.ai/v1/systemone`. See the
[TypeSafe Choice reference](https://docs.typesafe.ai/primitives/choice).
No key is stored in source, routing traces or the public configuration example.
Routing failures start no worker and do not silently fall back to the slower
Luna review loop. Each private job directory records the route and duration in
`dispatch-0/router.json` and preserves the worker's ordinary traces.

The default remains `dispatcher_mode: legacy` until a deployment explicitly
configures and verifies its Jev key. Each job pins its routing mode before work,
so changing configuration cannot switch an in-flight task's execution protocol.

## Ordered conversation lanes

With `dispatcher_mode: jev`, the laptop agent service uses up to four execution
slots by default (`agent_execution_slots`, integer 1–8). New tasks share one
serial general lane. Explicit `resume_task.root_id` follow-ups use the existing
context directly: no generic classification, Jev request or Luna review. Separate
contexts can answer concurrently while a new task is running; turns in the same
context retain receipt order. All turns remain durable in the agent store.

The relay transaction fences each active context and keeps a follow-up behind
its unfinished original task. Historical roots sharing the same recorded CLI
session share a lane too. Laptop context locks add a second fence: cancellation
or lease expiry cannot make a replacement turn overlap a still-stopping CLI.
The existing lease renewal, cancellation and durable result outbox remain in use.
The service holds one process singleton and records independent slot status files
beside the original execution ledger.

Parallel claims explicitly send `session_lanes: true` to the agent claim endpoint.
Omitting it retains the old globally serial contract. An older relay rejecting
that field causes the client to fall back to serial claims without losing tasks.
Legacy Luna mode also uses serial claims because its historical automatic resume
logic can select an existing session during classification. The programmatic
queue's claim and execution behavior is unchanged.

## Legacy Luna mode

The sections below describe the retained `legacy` mode and shared queue contracts.

## Incremental answers

`answer_streaming: true` enables genuine model deltas. Codex uses the local
app-server protocol and resumes the same saved thread; Claude uses partial-message
events. Background uploads coalesce readable answer snapshots without blocking
model reception. The relay stores sequence/versioned snapshots under the job's
existing lease. Superseded attempts and completed/cancelled jobs cannot publish
more text. Missing streaming support never prevents the final answer transport.

Task details and coach chats use versioned long polls, with no replay requirement
after reconnection. Money conversations expose the partial answer alongside their
existing final response fields. Structured specialist output streams only its
answer text, not memory, reasoning, tool arguments, financial decisions or workout
proposals. Mutations retain their complete-response validation and approval rules.
Streaming changes when text becomes visible; it does not guarantee faster model
startup. The normal final answer remains authoritative.

The cloud relay keeps two independent SQLite stores: `queue.sqlite3` for
programmatic commands and `agent-queue.sqlite3` for agent prompts. The second
queue is a FIFO inbox ordered by receipt, with at most one live lease. An expired
lease returns the oldest unfinished prompt to the head of that inbox. The two
workers have separate heartbeats and ledgers, so long agent tasks do not block
calendar queries. Shopping mutations remain immediate cloud transactions.

General agent prompts are sent to `/relay/v1/agent/prompts`. The existing
programmatic endpoint remains `/relay/v1/commands`; today its laptop executor is
the calendar reader. Submit/read/cancel/history use the owner submit credential;
claim/renew/results use the separate worker credential. Native voice programmed
actions run first; unmatched utterances enter the agent inbox with their original
text. The local dashboard Requests form uses the same inbox. Received WhatsApp
messages do not execute tasks.

Cloud-owned phone status notifications update one tagged card per task, including
queued requests while the laptop is unavailable. The card's Details link opens the
signed read-only phone task view without another sign-in. See `docs/phone-task-status.md` for
configuration, persistent retry behavior and delivery verification limits.

The supervised agent worker runs on the laptop. It resumes the explicit session
ID in its protected `orchestrator/session.json` for every accepted prompt and
every worker-result review. The dispatcher is **GPT-6 Luna, low effort**. It
returns a structured decision: dispatch workers, complete, or request missing
information. Luna selects the model, effort, working directory, task instructions,
expected artifacts and any known worker session to resume. Ordinary code validates
the decision and launches the CLI. No text parser selects the model.

The dispatcher receives `skills/*/SKILL.md` names, descriptions and absolute paths,
and selects a task type and skill names for each assignment. Email assignments
always receive `skills/email/SKILL.md` in full, even if the dispatcher omits that
name. Worker instructions include the catalog for additional skill selection and
references resolve against the skill folder. Skills do not install into global
CLI configuration. Account metadata, communication preferences and logs stay
private; generic workflows remain reusable.

Requests to get, send or download a specific file to the phone ("send me the March
invoice PDF", "get me the slides from my thesis folder") select
`skills/send-to-phone/SKILL.md`, together with the email skill when the file is an
attachment. The worker locates the file, sends it with `scripts/send_to_phone.py`
using a task-derived stable ID, and reports the relay state; ambiguous matches
return needs_input. Files are sent only on the owner's request, never in bulk or by
a background scan.

CLI workers explicitly enable apps/plugins and use existing ChatGPT authentication.
An already connected Gmail plugin is available to live searches and thread reads;
the archive is supplementary. Independent unattended crawls use separate OAuth
credentials. The dispatcher disables native subagent, app and shell tools and
receives the dispatch protocol on every resumed turn; ordinary service code owns
worker launches, selected-skill records and output traces. This keeps delegation
inside the recorded queue workflow.

Worker CLI calls use full-computer access and no interactive approvals, as selected
by the owner. Dependencies and logs remain organized in task directories; those
directories are not filesystem restrictions. Workers may use the approved Luna,
Sol and Astra model family and their supported effort settings. Assignments within
one decision currently execute sequentially. Luna does not need a permanently
running model process: `codex exec resume <session-id>` provides the continuity.

Workers run on one of two agents, named in each assignment. `codex` workers use
Luna, Sol or Astra through `codex exec`. `claude` workers run headless Claude Code
(`claude -p --output-format stream-json`) with Haiku, Sonnet, Opus or Fable and efforts
low to max, using the laptop's Claude subscription login rather than an API key. They
share the same record, trace, cancellation and recovery contract. The model must
belong to its agent. Continuations resume the session on the agent that started it.
Only codex workers have the connected Gmail plugin, so email tasks stay on codex. The
Claude executable is found on `PATH` or in `~/.local/bin`; set `claude` in the worker
config to pin it.

Every dispatcher turn, both the first decision and each results review, carries an
`agent_capacity` snapshot with each agent's remaining five-hour and weekly allowance,
reset times and any reached limit, so Luna never has to check usage itself.
- **Codex** figures come from the newest rate-limit record in the local Codex session
  logs (`CODEX_HOME`, or `codex_home` in the worker config).
- **Claude** figures come from the `rate_limit_event` of each headless Claude run, cached
  in the orchestrator folder. With `claude_capacity_refresh: true` in the worker config,
  figures older than an hour trigger a background one-line Haiku call, at most every
  30 minutes.

When both agents suit a task, Luna chooses the one with more remaining allowance and
avoids an agent whose five-hour window is under 20% or weekly window under 10%.
Missing or unreadable figures report `available: false` and never block dispatch.

## Claude stand-in while Codex is out of allowance

The dispatcher itself falls back to Claude, as the workout coach does. `dispatcher_engine`
(`auto`, `codex` or `claude`; default `auto`) selects it. In `auto`, each dispatcher turn
runs on Luna unless Codex is unusable: its capacity reading shows a window at 0% or a
reached limit, its executable is missing, or a usage-limit error put it in a cooldown
(`dispatcher_engine_retry_minutes`, default 30, kept in `engines.json` in the orchestrator
folder). A Luna turn that fails on the usage limit is retried once on Claude in the same
job. Only Codex error events and stderr count as a limit, never answer text. The Claude
turn is headless Claude Code with `dispatcher_claude_model` (default `claude-sonnet-5-5`)
at `dispatcher_claude_effort` (default `low`), the same protocol and Decision schema
(`--json-schema`), no built-in tools, MCP servers or skills, and its own session in
`claude-session.json`, resumed by later Claude turns. Luna's `session.json` is untouched.
A crash-recovered turn reuses whichever agent's decision was already recorded.

Every turn carries `agent_availability`. While Codex is unusable, code also replaces each
codex assignment with its Claude tier before any worker starts (Luna to Haiku, Terra to
Sonnet, Sol/Astra to Opus, ultra to max) and records `substituted_from` on the worker. Such a
worker starts a fresh session: a Codex session cannot move to Claude. Email assignments
need the Codex Gmail plugin, so they return needs_input with the reset time instead. A
follow-up on a Codex task while Codex is unusable, or whose Codex turn hit the limit
before doing anything (no command, tool or file items in its trace), continues in a fresh
Claude session at the same tier; that session then becomes the task's session for later
follow-ups. A worker that hits the limit mid-run is not repeated: it needs review as
before, and its agent cools down. When neither agent can run, the task returns
needs_input without starting anything.

## Resuming earlier sessions without a Reply

An explicit follow-up (Reply, or a task-page instruction) resumes its task's session
directly. A newly enqueued prompt can also continue earlier work: the first dispatcher
turn carries `recent_tasks`, the newest finished tasks (at most 12, up to 7 days old,
about 8,000 characters). Each entry gives the task ID, request and finish times, the
truncated request and outcome summary, and each worker's agent, model, effort,
workspace, task type, skills and session ID. A session is listed once, at its
newest task. Left out: background mail scans, the Luna session itself, tasks needing
reconciliation, and sessions whose newer use was interrupted or failed. The
`recent_task_limit`, `recent_task_days` and `recent_task_chars` worker config keys
change the bounds.

Luna resumes a listed session only when the new request clearly continues that task
(same files, thread or topic, "also", "now do X to it", a correction or an answer),
prefers an explicit `followup_context` link, never resumes across unrelated topics,
and names the reused task in its summary. Code accepts `resume_session` only from
this job's own results or the listed sessions. An earlier session must keep its
agent, its model (its context was built by that model) and its workspace (Claude
resolves sessions per project directory); effort may change. Guessed IDs and any
mismatch are rejected before any worker of that decision starts, and so is a relative
workspace. Whether a workspace exists is checked just before its worker launches, so
an earlier assignment of the same decision may create it; each finished worker is
saved to `job.json` at once, so a later refused or interrupted sibling cannot drop
its result. `job.json` keeps the list Luna saw, `resumed_from_task` (the earlier task
IDs) and the same field on each resumed worker.

## Forwarding assistant development

Requests to build, change, fix, debug, review, release or deploy the assistant itself
(this repository: Companion app, dashboard, relay/server, orchestrator, skills, tests,
docs, releases) go to the owner's interactive development sessions, one Claude Code
and one Codex, instead of headless workers. Requests that merely use the assistant
(calendar, email, shopping, files, research, phone actions) are dispatched as usual.
Luna returns `action: forward` with `forward_to: claude|codex` and no tasks; every
other action carries `forward_to: none`, and code rejects any other combination. An
explicitly named agent wins; otherwise Luna picks the one with more `agent_capacity`.
A forward is accepted only as the first decision, before any worker runs: the message
carries just the owner's request, so a forward from a results review returns
needs_input with `reconciliation_required` and the saved worker results. A follow-up
on a forwarded task (Reply or task-page instruction) is not run headlessly: it returns
needs_input naming the development session and message ID. A forwarded outcome carries
no Luna session ID.

Delivery uses a local coordination bridge outside this repository. Its private
config (`coordination_config`, default `~/.personal-assistant/coordination/config.json`)
holds the port, bearer token and session IDs; the orchestrator reads the port and
token only to send, bypasses proxies, and never logs or stores the token. The first
dispatcher turn receives `dev_forwarding.available` when that config exists. Code,
not Luna, writes the message: the task ID, request time and timezone, the owner's
request verbatim, a `Request SHA-256:` line over it, any follow-up context, Luna's
routing note, and a request to report directly to the owner. The sender is
`dev_forward_sender` (default `luna`). The message ID is a UUIDv5 of the task ID, so
a retry or crash recovery never sends twice. The bridge labels it a claim. Before
acting, the receiving session runs `scripts/verify_forwarded_task.py <task> --sha256
<hex>` against the authorized queue entry.

`job.json` records the message ID, digest and the bridge's answer (ID and status,
never the token). A transmitted, accepted or queued message (the session is offline
and the bridge retries) completes the task with that status in the summary. A
missing config, an unreachable bridge, a non-2xx answer, or an `uncertain` or
`failed` status returns needs_input with the message ID and `reconciliation_required`.
A missing config, a connection that cannot be made or a non-2xx answer is a definite
failure (record `failed`; resubmit). A timeout, or a connection the bridge drops after
receiving the request (no or malformed answer), is `uncertain`: check the message ID
before resubmitting.
A crash recovery keeps the earlier record and its first attempt time; when an earlier
attempt may have reached the bridge, a failed retry is also reported as `uncertain`.

## Submit a task

```powershell
.venv/Scripts/python.exe scripts/submit_agent_task.py --prompt-file PRIVATE_PROMPT_FILE --workspace ABSOLUTE_WORKING_DIRECTORY
```

The working directory is optional. Add `--wait` to wait for the terminal result;
without it the script returns the durable server acknowledgement immediately.
Supply a stable `--id` when retrying: the original envelope and timestamp are saved
under the protected agent runtime. The legacy `run_coding_task.py` and public lab
launcher now submit to this same inbox rather than launching a worker directly.
Its former CLI executable arguments are compatibility arguments; the supervised
service uses the executable in its protected configuration.

## History and recovery

Each queue job has its cloud event history, a local execution ledger, and an
`orchestrator/jobs/<job-id>/job.json`. Each dispatcher turn and worker call stores
its prompt, JSONL stream, stderr, final response, explicit session ID, selected
model/effort, timestamps, exit state and emitted usage. Worker results and artifact
existence/checksums are persisted before returning them to Luna. Luna reviews them
before replying to the user. Logs provide recovery; they do not expose private
internal reasoning or guarantee that a model's claims are correct.

Acknowledgement retries reuse stored outcomes. A call with a terminal stream and
saved result can recover after a crash before its acknowledgement. An interrupted
call with uncertain effects is **not blindly run again**: it becomes needs_input
with its trace preserved for reconciliation. External side effects cannot be
guaranteed exactly once. The first session ID can be recovered from its initial
stream if a crash happened before session metadata was saved. A failed resume does
not silently replace Luna's session with a new one.

The shared laptop pause control pauses both queues; each worker can also be paused
independently with its own runtime `pause.flag`. Cancellation/expiry invalidates
the lease and signals the CLI process tree to stop. It does not undo prior effects.
Per-call timeout is configurable (default 30 minutes); the current follow-up loop
permits eight delegation rounds before returning a saved-progress needs_input.

Validated with real CLI/model calls: two cloud prompts used the same Luna session,
spawned workers with the requested model/effort, wrote two checked artifacts, and
the second prompt recalled the first. A programmatic calendar query completed
while both agent prompts remained queued. Tests cover queue separation, serial
claims, stale leases, cancellation, cached outcomes and interrupted-call recovery.

## Task attachments

Companion uploads originals to the paired, streaming
`PUT /groceries/v1/mobile/task-attachments/{id}` route. Its base64 UTF-8 JSON
`X-Attachment-Manifest` contains `name`, `mime`, `size` and `sha256`. Uploads are
bounded to 25 MiB and verified before becoming available. Task submission uses
`POST /groceries/v1/mobile/tasks` with `id`, `text`, `created_at`, `timezone` and
`attachments` (up to ten uploaded IDs). The existing paired follow-up endpoint
accepts the same optional `attachments` list. Stable envelope and file IDs make
acknowledgement retries idempotent, including same-session follow-ups.

The worker downloads associated originals through authenticated
`/relay/v1/agent/attachments/{id}` metadata and `/content` routes, into its private
job `attachments/` directory. Verified local paths reach Luna, every assigned
worker, resumed sessions and the development-session forwarding message. Files
remain data; they cannot override the user's instruction. These API operations
alone make no model calls. Legacy owner web follow-ups reject attachment IDs;
use Companion's paired uploader to associate and validate them.

For file deliverables, every new worker and same-session continuation receives
the current job ID and the `scripts/attach_task_file.py FILE --task JOB_ID` helper.
The helper streams the selected original to the service-authenticated
`PUT /relay/v1/agent/tasks/{job}/attachments/{id}` endpoint. The relay verifies the
manifest/checksum, retains it, and records it as an answer attachment of that exact
job. Native details expose separate `response_attachments` for the original answer
and every continuation. Upload retries preserve IDs and do not duplicate files.
No directory scanning or automatic collection of logs/intermediate files occurs.
The worker must explicitly select requested deliverables and check upload success.
