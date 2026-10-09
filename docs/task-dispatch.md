# Two queues and one Luna session

The cloud relay keeps two independent SQLite stores: `queue.sqlite3` for
programmatic commands and `agent-queue.sqlite3` for agent prompts. The second
queue is a FIFO inbox ordered by receipt, with at most one live lease. An expired
lease returns the oldest unfinished prompt to the head of that inbox. The two
workers have separate heartbeats and ledgers, so long agent tasks do not block
calendar queries. Shopping mutations remain immediate cloud transactions.

General agent prompts are sent to `/relay/v1/agent/prompts`. The existing
programmatic endpoint remains `/relay/v1/commands`; today its laptop executor is
the calendar reader. Submit/read/cancel/history use the owner submit credential;
claim/renew/results use the separate worker credential. Home Assistant's Personal
assistant and built-in Home Assistant pipelines use `conversation.assistant_dispatch`: programmed/native
behavior runs first, and unmatched utterances or unresolved native targets go
directly to the agent inbox. A broad native sentence match with no matching device
must not swallow an ordinary request such as following up on email threads.
No `ask my assistant` or `queue` prefix is required. The exact utterance is retained.
Known programmed-action failures and responses with attempted target results are
returned without a second execution path.
The local dashboard's Requests form submits directly to the same inbox. Received
WhatsApp messages do not execute tasks.

`scripts/configure_homeassistant_dispatch.py` applies this routing through the
authenticated pipeline API, backing up the prior settings and retaining pipeline
IDs, languages and speech providers. It also disables `prefer_local_intents`,
because the dispatcher already runs native behavior first. A cached phone
selection of the built-in pipeline must not bypass Luna. The voice setup script
uses this same configuration; rerunning it must not restore a native-only agent.
Pipelines deliberately using another conversation provider are left unchanged.

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
