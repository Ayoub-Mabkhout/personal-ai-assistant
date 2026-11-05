# Managed cloud execution pilot

The relay keeps task state and app data. The managed agent runs in the
provider's environment and calls the relay over Streamable HTTP MCP. This
pilot uses fresh fixture databases and a single job with a five-minute
lease. It has no access to production accounts or data.

1. In a disposable Python environment, install the project with the server
   extra and the MCP SDK (`pip install -e ".[server]" "mcp==1.30.0"`).
   Set `ASSISTANT_CLOUD_PILOT_TOKEN` to a random secret of at least 32
   characters and run `python scripts/managed_cloud_pilot.py state/cloud-pilot/run-1`.
   The directory must be new. The service binds to loopback on port 8799.
2. For a provider run, serve `/mcp` through a temporary HTTPS route on the
   pilot host. Forward the Authorization header and use
   `127.0.0.1:8799` as the upstream Host header. Configure the MCP URL and
   bearer token in the provider's managed environment. Keep the token out of
   prompts and source files. Remove the route and token after the run.
3. Ask the agent to call `report_progress` with sequence 0, then
   `add_pilot_grocery`, and finally `finish_task` with what changed.
   Verify the existing mobile task read model returns the progress and
   final summary and that the fixture grocery list contains one item.

Before routing live requests, record the provider job/session ID against the
existing task ID and test two turns in the same provider session. Verify
model/effort controls, delivery after a laptop shutdown, and how failures
or expired leases are reported. Treat agent-written progress snapshots as
progress, and verify provider text deltas separately before enabling streaming.
