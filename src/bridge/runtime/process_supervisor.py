# AI生成
"""Process supervisor: spawn, track, cancel, and kill worker processes.

Provides real Worker lifecycle control:
  RUNNING -> CANCEL_REQUESTED -> terminate -> grace period -> kill -> CANCELLED
"""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..state import get_state, set_state, RUNNING, CANCEL_REQUESTED, CANCELLED


@dataclass
class TrackedProcess:
    """A tracked worker process."""
    task_id: str
    pid: int
    started_at: float
    cancelled_at: float | None = None


class ProcessSupervisor:
    """Manages worker process lifecycle.

    Usage:
        sup = ProcessSupervisor()
        sup.spawn(task_id, cmd)
        sup.cancel(task_id, task_dir, grace_seconds=10)
    """

    def __init__(self) -> None:
        self._tracked: dict[str, TrackedProcess] = {}

    def track(self, task_id: str, pid: int) -> None:
        """Register a spawned process for tracking."""
        self._tracked[task_id] = TrackedProcess(
            task_id=task_id,
            pid=pid,
            started_at=time.time(),
        )

    def untrack(self, task_id: str) -> None:
        """Remove a task from tracking."""
        self._tracked.pop(task_id, None)

    def is_tracked(self, task_id: str) -> bool:
        return task_id in self._tracked

    def cancel(
        self,
        task_id: str,
        task_dir: str | Path,
        grace_seconds: float = 10.0,
    ) -> dict[str, Any]:
        """Cancel a tracked worker process.

        1. Set CANCEL_REQUESTED state
        2. Send SIGTERM (graceful)
        3. Wait grace period
        4. Send SIGKILL if still alive
        5. Set CANCELLED state

        Idempotent: if already CANCELLED, returns immediately.
        """
        task_dir = Path(task_dir)

        # Idempotent: check current state
        state = get_state(task_dir)
        if state.get("status") == CANCELLED:
            return {"taskId": task_id, "state": CANCELLED, "message": "already cancelled"}

        # Step 1: CANCEL_REQUESTED
        set_state(task_dir, CANCEL_REQUESTED, message="cancel requested")

        proc = self._tracked.get(task_id)
        if not proc:
            # No tracked process — just mark CANCELLED
            set_state(task_dir, CANCELLED, message="cancelled (no tracked process)")
            return {"taskId": task_id, "state": CANCELLED, "message": "no tracked process"}

        proc.cancelled_at = time.time()
        pid = proc.pid

        # Step 2: SIGTERM
        terminated = False
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            terminated = True

        if not terminated:
            # Step 3: grace period
            deadline = time.time() + grace_seconds
            while time.time() < deadline:
                if not _is_alive(pid):
                    terminated = True
                    break
                time.sleep(0.5)

        # Step 4: SIGKILL if still alive
        if not terminated:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        # Step 5: CANCELLED
        set_state(task_dir, CANCELLED, message=f"cancelled (pid {pid})")
        self.untrack(task_id)

        return {"taskId": task_id, "state": CANCELLED, "pid": pid}

    def reap(self) -> list[str]:
        """Remove tracked processes that have exited."""
        reaped = []
        for task_id, proc in list(self._tracked.items()):
            if not _is_alive(proc.pid):
                self.untrack(task_id)
                reaped.append(task_id)
        return reaped


def _is_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False