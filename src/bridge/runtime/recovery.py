# AI生成
"""Stale session recovery for runtime supervisor.

Detects sessions that are marked active but whose process is gone,
or whose heartbeat is stale, and marks them appropriately.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..atomic import read_json_or_none
from .heartbeat import is_stale, read_heartbeat
from .session import Session, load_session, end_session


def find_stale_sessions(
    runtime_dir: Path,
    stale_heartbeat_minutes: int = 5,
) -> list[Session]:
    """Find all sessions that are active but likely stale."""
    sessions_dir = Path(runtime_dir) / "sessions"
    if not sessions_dir.exists():
        return []

    stale = []
    for p in sessions_dir.glob("*.json"):
        data = read_json_or_none(p)
        if not data or data.get("status") != "active":
            continue

        session = Session.from_dict(data)
        task_id = session.task_id

        # Check heartbeat staleness
        if is_stale(runtime_dir, task_id, stale_heartbeat_minutes):
            stale.append(session)
            continue

        # Check if PID is still alive
        pid = session.pid
        if pid is not None:
            if not _is_pid_alive(pid):
                stale.append(session)

    return stale


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    try:
        import os
        os.kill(pid, 0)  # Signal 0 = check existence
        return True
    except (ProcessLookupError, OSError):
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it


def recover_stale_sessions(
    runtime_dir: Path,
    stale_heartbeat_minutes: int = 5,
) -> list[str]:
    """Mark stale sessions as failed and return their task IDs."""
    stale = find_stale_sessions(runtime_dir, stale_heartbeat_minutes)
    recovered = []
    for session in stale:
        end_session(
            runtime_dir,
            session.session_id,
            status="failed",
            exit_code=-1,
        )
        recovered.append(session.task_id)
    return recovered


def find_orphaned_leases(runtime_dir: Path) -> list[str]:
    """Find leases whose sessions are no longer active."""
    leases_dir = Path(runtime_dir) / "leases"
    sessions_dir = Path(runtime_dir) / "sessions"

    if not leases_dir.exists():
        return []

    active_task_ids = set()
    if sessions_dir.exists():
        for p in sessions_dir.glob("*.json"):
            data = read_json_or_none(p)
            if data and data.get("status") == "active":
                active_task_ids.add(data.get("taskId", ""))

    orphaned = []
    for p in leases_dir.glob("*.json"):
        data = read_json_or_none(p)
        if not data:
            continue
        task_id = data.get("taskId", "")
        if task_id and task_id not in active_task_ids:
            orphaned.append(task_id)

    return orphaned
