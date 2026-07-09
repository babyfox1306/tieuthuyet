"""In-memory batch job tracking.

Keep this module out of importlib.reload() — reloading would orphan running
threads and make every batch poll look like a server crash.
"""

from __future__ import annotations

import threading

_batch_threads: dict[str, threading.Thread] = {}
_batch_sync_locks: set[str] = set()


def batch_is_active(workspace_id: str) -> bool:
    if workspace_id in _batch_sync_locks:
        return True
    thread = _batch_threads.get(workspace_id)
    return thread is not None and thread.is_alive()


def register_thread(workspace_id: str, thread: threading.Thread) -> None:
    _batch_threads[workspace_id] = thread


def unregister_thread(workspace_id: str) -> None:
    _batch_threads.pop(workspace_id, None)


def add_sync_lock(workspace_id: str) -> None:
    _batch_sync_locks.add(workspace_id)


def discard_sync_lock(workspace_id: str) -> None:
    _batch_sync_locks.discard(workspace_id)
