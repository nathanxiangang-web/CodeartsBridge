# AI生成
"""Cancellation handling for runtime supervisor.

Supports graceful cancellation: SIGTERM → grace period → SIGKILL.
Cancellation requests are persisted so they survive bridge restarts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..atomic import atomic_write_json, read_json_or_none


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_cancellation(runtime_dir: Path, task_id: str, reason: str = "") -> None:
    """Write a cancellation request for a task."""
    cancel_dir = Path(runtime_dir) / "cancellations"
    cancel_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "taskId": task_id,
        "reason": reason,
        "requestedAt": _now_iso(),
        "status": "pending",
    }
    atomic_write_json(cancel_dir / f"{task_id}.json", data)


def get_cancellation(runtime_dir: Path, task_id: str) -> dict | None:
    """Read a cancellation request."""
    path = Path(runtime_dir) / "cancellations" / f"{task_id}.json"
    return read_json_or_none(path)


def is_cancelled(runtime_dir: Path, task_id: str) -> bool:
    """Check if a task has a cancellation request."""
    data = get_cancellation(runtime_dir, task_id)
    return data is not None


def complete_cancellation(runtime_dir: Path, task_id: str, exit_code: int) -> None:
    """Mark cancellation as completed."""
    path = Path(runtime_dir) / "cancellations" / f"{task_id}.json"
    data = read_json_or_none(path)
    if data is None:
        return
    data["status"] = "completed"
    data["completedAt"] = _now_iso()
    data["exitCode"] = exit_code
    atomic_write_json(path, data)


def remove_cancellation(runtime_dir: Path, task_id: str) -> None:
    """Remove cancellation record after cleanup."""
    path = Path(runtime_dir) / "cancellations" / f"{task_id}.json"
    if path.exists():
        path.unlink()


def get_pending_cancellations(runtime_dir: Path) -> list[str]:
    """Get all task IDs with pending cancellation requests."""
    cancel_dir = Path(runtime_dir) / "cancellations"
    if not cancel_dir.exists():
        return []
    result = []
    for p in cancel_dir.glob("*.json"):
        data = read_json_or_none(p)
        if data and data.get("status") == "pending":
            result.append(data.get("taskId", p.stem))
    return result
