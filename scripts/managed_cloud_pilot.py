"""Run one isolated managed-agent round trip over Streamable HTTP MCP."""

import argparse
import os
import secrets
from pathlib import Path
from threading import Lock
from uuid import uuid4

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import Response

from personal_assistant.groceries.store import Groceries
from personal_assistant.relay.answer_streams import Snapshot, queue_snapshot
from personal_assistant.relay.store import Queue


def build_app(directory: Path, token: str):
    """Create fresh fixture stores and bind the endpoint to one queue lease."""
    if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError("Use a randomly generated ASCII bearer token of at least 32 characters.")
    directory.mkdir(parents=True, exist_ok=False)
    queue = Queue(directory / "jobs.sqlite3", serial=True)
    groceries = Groceries(directory / "groceries.sqlite3")
    job_id = uuid4().hex
    queue.submit({"id": job_id, "command": "Add pilot oats to the fixture shopping list.",
                  "timezone": "UTC"}, source="managed_cloud_pilot")
    lease = None
    lock = Lock()

    def job_lease():
        nonlocal lease
        with lock:
            if lease is None:
                queue.heartbeat("ready")
                lease = queue.claim(300)["lease_token"]
            return lease
    mcp = FastMCP("Assistant cloud pilot", stateless_http=True, json_response=True)

    @mcp.tool()
    def add_pilot_grocery() -> dict:
        """Add pilot oats to the disposable grocery list. Safe to retry."""
        token = job_lease()
        with queue.connection(write=True) as db:
            queue.owned(db, job_id, token)
            return groceries.mutate({"id": job_id, "operation": "add",
                                     "items": [{"name": "pilot oats"}]})

    @mcp.tool()
    def report_progress(sequence: int, text: str) -> dict:
        """Publish a user-visible progress snapshot. Start sequence at zero."""
        return queue_snapshot(queue, job_id, Snapshot(token=job_lease(), sequence=sequence, text=text))

    @mcp.tool()
    def finish_task(answer: str) -> dict:
        """Save the final answer in the existing task result format."""
        if not answer.strip() or len(answer) > 24000:
            raise ValueError("Supply a non-empty answer of up to 24000 characters.")
        result = queue.finish(job_id, job_lease(), "completed", {"summary": answer})
        return {"id": result["id"], "state": result["state"]}

    app = mcp.streamable_http_app()
    expected = b"Bearer " + token.encode("ascii")

    async def authenticated(scope, receive, send):
        if scope["type"] == "http":
            credentials = [v for k, v in scope["headers"] if k == b"authorization"]
            if len(credentials) != 1 or not secrets.compare_digest(credentials[0], expected):
                response = Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
        await app(scope, receive, send)

    return authenticated, job_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture_directory", type=Path, help="A new directory for disposable data")
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args()
    token = os.environ.get("ASSISTANT_CLOUD_PILOT_TOKEN", "")
    app, job_id = build_app(args.fixture_directory, token)
    print(f"Pilot job {job_id}, five-minute lease starts on first tool call", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
