# AI生成
"""Task service: task creation, status查询, cancellation.

Application-layer service that orchestrates core models, state machine,
and file I/O for task management.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_text, atomic_write_json, read_json_or_none
from ..core.state import get_state, set_state, CREATED, READY, CANCELLED
from ..core.ids import generate_assignment_id
from ..core.errors import TaskNotFoundError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_task(
    bridge_root: Path,
    project_id: str,
    worker_id: str | None,
    role: str,
    task_id: str,
    task_file: str | None,
    required_skills: list[str] | None = None,
    depends_on: list[str] | None = None,
    priority: int = 0,
    preferred_worker: str | None = None,
    excluded_workers: list[str] | None = None,
    review_required: bool = True,
    independent_review: bool = True,
) -> dict:
    """Create a new task with v2 META schema."""
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    if task_dir.exists():
        raise ValueError(f"Task already exists: {task_id}")

    # Read task content. The public CLI/UI contract allows task_file to be omitted.
    if task_file:
        task_path = Path(task_file)
        if not task_path.is_file():
            raise ValueError(f"Task file not found: {task_file}")
        task_content = task_path.read_text(encoding="utf-8")
    else:
        task_content = "# TASK\n\n(No task file provided)\n"

    # Create directories
    (task_dir / "inbox").mkdir(parents=True)
    (task_dir / "outbox").mkdir(parents=True)

    # Write META.json (v2 schema)
    meta = {
        "schemaVersion": 2,
        "taskId": task_id,
        "projectId": project_id,
        "workerId": worker_id,
        "role": role,
        "requiredSkills": required_skills or [],
        "dependsOn": depends_on or [],
        "priority": priority,
        "createdAt": _now_iso(),
        "execution": {
            "preferredWorker": preferred_worker,
            "excludedWorkers": excluded_workers or [],
        },
        "review": {
            "required": review_required,
            "independentWorker": independent_review,
        },
    }
    atomic_write_json(task_dir / "META.json", meta)

    # Write task content to inbox
    atomic_write_text(task_dir / "inbox" / "001-TASK.md", task_content)

    # Write initial state
    set_state(task_dir, CREATED)
    set_state(task_dir, READY)

    return meta


def get_task_status(bridge_root: Path, task_id: str) -> dict:
    """Get full task status including state and meta."""
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    if not task_dir.exists():
        raise TaskNotFoundError(f"Task not found: {task_id}")

    state_data = get_state(task_dir)
    state = state_data.get("state", CREATED)
    meta = read_json_or_none(task_dir / "META.json")
    worker_id = (meta or {}).get("workerId") or state_data.get("assignedWorkerId")

    return {
        "taskId": task_id,
        "state": state,
        "workerId": worker_id,
        "meta": meta,
    }


def cancel_task(bridge_root: Path, task_id: str, reason: str = "") -> dict:
    """Cancel a task."""
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    if not task_dir.exists():
        raise TaskNotFoundError(f"Task not found: {task_id}")

    current = get_state(task_dir).get("state", CREATED)
    if current in ("DONE", CANCELLED):
        return {"taskId": task_id, "state": current, "message": "already terminal"}

    set_state(task_dir, CANCELLED)

    # Write cancellation record
    cancel_record = {
        "taskId": task_id,
        "reason": reason,
        "cancelledAt": _now_iso(),
    }
    atomic_write_json(task_dir / "cancellation.json", cancel_record)

    return {"taskId": task_id, "state": CANCELLED, "reason": reason}


def list_tasks(bridge_root: Path, state_filter: str | None = None) -> list[dict]:
    """List all tasks, optionally filtered by state."""
    bridge_root = Path(bridge_root)
    tasks_dir = bridge_root / "tasks"
    if not tasks_dir.exists():
        return []

    results = []
    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        task_id = task_dir.name
        state_data = get_state(task_dir)
        state = state_data.get("state", CREATED)
        if state_filter and state != state_filter:
            continue
        meta = read_json_or_none(task_dir / "META.json")
        worker_id = (meta or {}).get("workerId") or state_data.get("assignedWorkerId")
        results.append({
            "taskId": task_id,
            "state": state,
            "projectId": meta.get("projectId") if meta else None,
            "workerId": worker_id,
            "role": meta.get("role") if meta else None,
        })
    return results
