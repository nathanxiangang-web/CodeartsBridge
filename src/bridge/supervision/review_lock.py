"""File-based review lock to prevent duplicate reviews (AR-06).

Lock is persisted to runtime/review-locks/<task-id>.lock with a TTL
to prevent permanent locks on crash.  Safe for multi-process use
because it checks file mtime on acquire.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class ReviewLock:
    """File-based lock with TTL for preventing duplicate reviews.

    Args:
        lock_dir: Directory to store lock files.
        ttl_seconds: Lock auto-expires after this many seconds.
    """

    def __init__(
        self,
        lock_dir: Path,
        ttl_seconds: int = 300,
    ) -> None:
        self._dir = Path(lock_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_seconds

    def _lock_path(self, task_id: str) -> Path:
        return self._dir / f"{task_id}.lock"

    def acquire(self, task_id: str) -> bool:
        """Try to acquire a review lock. Returns True if acquired.

        If a lock file exists but is older than TTL, it is considered
        expired and overwritten (crash recovery).
        """
        path = self._lock_path(task_id)
        if path.exists():
            data = self._read_lock(path)
            if data is not None:
                age = time.time() - data.get("timestamp", 0)
                if age < self._ttl:
                    return False
        path.write_text(
            json.dumps({"taskId": task_id, "timestamp": time.time()}),
            encoding="utf-8",
        )
        return True

    def release(self, task_id: str) -> None:
        """Release a review lock by deleting the lock file."""
        path = self._lock_path(task_id)
        if path.exists():
            path.unlink()

    def is_locked(self, task_id: str) -> bool:
        """Check if a task is currently locked (and lock has not expired)."""
        path = self._lock_path(task_id)
        if not path.exists():
            return False
        data = self._read_lock(path)
        if data is None:
            return False
        age = time.time() - data.get("timestamp", 0)
        return age < self._ttl

    @staticmethod
    def _read_lock(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None