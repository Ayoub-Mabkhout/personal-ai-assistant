# Per-task coding workbench

Each task has a private workspace outside OneDrive, a Python venv, optional local
Node/TypeScript dependencies and package lock, task instructions, and an environment
inventory. Java, .NET, and PowerShell use installed host toolchains. Dependencies
are isolated per task; these directories share the OS account and are not security
sandboxes. Go/Rust are detected if installed, not automatically provisioned.

```powershell
.venv/Scripts/python.exe scripts/task_environment.py my-task --javascript
.venv/Scripts/python.exe scripts/check_task_environment.py --workspace "$env:USERPROFILE/.personal-assistant/lab/my-task"
```

The check compiles/runs small Python, JS, TS, Java, C# and PowerShell programs as
available and records `checks.json`. It leaves the generated examples under
`.checks/` for inspection. Use this task's Python executable, `node_modules`, and
project manifests for actual work. Install new dependencies only for the task
requiring them, preserving lockfiles and compiler requirements.

## Captured headless jobs

All new agent tasks now enter the dedicated cloud inbox and the same persistent
Luna dispatcher. See [task dispatch](task-dispatch.md) for submission, session
continuity, worker selection, logs and recovery. The launcher below is a compatibility
entry point to that inbox; it does not spawn an independent CLI worker anymore.

The owner selected one persistent Luna coordinator for every agent task, together
with durable execution logs. Programmatic calendar queries and shopping do not need
model calls. Prompts, CLI events, stderr, results, selected model/effort, session IDs
and outcomes live under the protected orchestrator job directory. Actual CLI task
execution and resuming the same dispatcher session have been verified. CLI runs
use existing ChatGPT authentication and consume that account's model allowance.

```powershell
.venv/Scripts/python.exe scripts/submit_agent_task.py --workspace "$env:USERPROFILE/.personal-assistant/lab/my-task" --prompt-file PRIVATE_PROMPT_FILE --wait
```

The supervised service stores its CLI and Node executable paths in private config.
The owner explicitly selected full-computer access for headless agents. The runner
uses `exec --json --ignore-user-config --sandbox danger-full-access` with
`approval_policy="never"`. These are local processes running as the current
Windows user, without a Codex filesystem/network sandbox. Ordinary Windows account
permissions still apply; the flag does not make the process an administrator.
Task directories organize dependencies and traces rather than restricting access.
The runner never supplies an API key. Common assistant/cloud/API secret environment variables
are excluded from the child environment. Existing saved CLI authentication remains
in the CLI's protected home; transcripts may contain task data and must remain private.

The programmatic cloud worker supports calendar queries. A separate supervised
agent worker now resumes Luna and launches the assignments it selects.
Creating a subprocess does not transfer its full history to the current chat.
[Official non-interactive CLI documentation](https://learn.chatgpt.com/docs/non-interactive-mode).
