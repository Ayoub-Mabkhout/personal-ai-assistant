"""In-process wake-ups for long-polling claims and conversation views.

The relay runs as one uvicorn process, so a version counter per key is enough to wake
waiting requests the moment work is enqueued. Waiters also re-check on a short slice,
which covers changes that are not signalled (lease expiry, delayed retries, another
process). Waiting happens on the event loop; the blocking SQLite work stays in the
threadpool, so idle long polls hold no worker threads.
"""
import asyncio
import logging
import threading
import time

MAX_WAIT_SECONDS = 25
RECHECK_SECONDS = 10
# Each waiting request holds a connection; keep well below uvicorn's --limit-concurrency.
MAX_WAITERS = 24


class Wakeups:
    def __init__(self):
        self._lock = threading.Lock()
        self._versions = {}
        self._waiters = {}

    def version(self, key):
        with self._lock:
            return self._versions.get(key, 0)

    def notify(self, *keys):
        pending = []
        with self._lock:
            for key in keys:
                self._versions[key] = self._versions.get(key, 0) + 1
                pending.extend(self._waiters.pop(key, ()))
        for loop, future in pending:
            try:
                loop.call_soon_threadsafe(_resolve, future)
            except RuntimeError:  # loop already closed
                pass

    async def wait(self, key, since, timeout):
        """Sleep until `key` changes after version `since`, or `timeout` elapses. True when changed."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        entry = (loop, future)
        with self._lock:
            if self._versions.get(key, 0) != since:
                return True
            self._waiters.setdefault(key, []).append(entry)
        try:
            await asyncio.wait_for(future, max(0.0, timeout))
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            with self._lock:
                waiters = self._waiters.get(key)
                if waiters and entry in waiters:
                    waiters.remove(entry)
                    if not waiters:
                        self._waiters.pop(key, None)


def _resolve(future):
    if not future.done():
        future.set_result(None)


class _Budget:
    def __init__(self, limit):
        self.limit, self.active, self.lock = limit, 0, threading.Lock()

    def acquire(self):
        with self.lock:
            if self.active >= self.limit:
                return False
            self.active += 1
            return True

    def release(self):
        with self.lock:
            self.active -= 1


budget = _Budget(MAX_WAITERS)


def requested_wait(value):
    """Clamp a client's ?wait= so old clients (no parameter) keep the immediate answer."""
    try:
        seconds = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if seconds != seconds or seconds <= 0:  # NaN or non-positive
        return 0.0
    return min(seconds, MAX_WAIT_SECONDS)


async def long_poll(attempt, wakeups, key, wait, request=None, recheck=RECHECK_SECONDS):
    """Run `attempt` (blocking) until it returns something truthy or `wait` seconds pass.

    Returns (result, honoured_wait). honoured_wait is 0 when the waiter budget is full, so a
    client knows to fall back to its own fixed poll interval instead of looping immediately.
    """
    from starlette.concurrency import run_in_threadpool  # server-only dependency
    seen = wakeups.version(key)
    result = await run_in_threadpool(attempt)
    if result or wait <= 0:
        return result, wait
    if not budget.acquire():
        return result, 0
    try:
        deadline = time.monotonic() + wait
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return result, wait
            await wakeups.wait(key, seen, min(remaining, recheck))
            # A client that went away must not be handed (and lease) a job it will never run.
            if request is not None and await request.is_disconnected():
                return None, wait
            seen = wakeups.version(key)
            result = await run_in_threadpool(attempt)
            if result:
                return result, wait
    finally:
        budget.release()


_timing = logging.getLogger('personal_assistant.timing')
if not _timing.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    _timing.addHandler(_handler)
    _timing.setLevel(logging.INFO)
    _timing.propagate = False


def log_phases(kind, label, phases):
    """One line per job with phase durations in seconds. Labels must not carry personal data."""
    parts = ' '.join(f'{name}={value:.2f}s' for name, value in phases if value is not None and value >= 0)
    _timing.info('%s %s %s', kind, label, parts)
