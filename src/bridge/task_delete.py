# AI生成
"""Task deletion: record cleanup, not execution control.

Delete != Cancel. Deleting a task record never kills a running Agent Job.
For running tasks, a deferred delete marker is written; the task is physically
removed after the Worker naturally finishes and Bridge completes cleanup.

See docs/ai-closeout/08-TASK-DELETION-SEMANTICS.md for the full spec.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .atomic import read_json_or_none
from .core.state import get_state, STARTING, RUNNING, VERIFYING, INTEGRATING, TERMINAL_STATES

logger = logging.getLogger(__name__)

MARKER_FILE = ".delete-requested"

_ACTIVE_EXECUTION_STATES = {STARTING, RUNNING, VERIFYING, INTEGRATING}


def _has_inflight(task_dir: Path) -> bool:
    return (task_dir / "inflight.json").exists()


def _has_active_assignment(bridge_root: Path, task_id: str) -> bool:
    assignments_dir = bridge_root / "runtime" / "assignments"
    if not assignments_dir.exists():
        return False
    for d in assignments_dir.iterdir():
        if not d.is_dir():
            continue
        data = read_json_or_none(d / "assignment.json")
        if data and data.get("taskId") == task_id and data.get("status", "active") == "active":
            return True
    return False


def is_delete_requested(task_dir: Path) -> bool:
    """Check if a task has a pending delete request."""
    return (Path(task_dir) / MARKER_FILE).exists()


def is_task_active(bridge_root: Path, task_id: str) -> bool:
    """Determine if a task has real active execution.

    True if any of:
    - state is in STARTING/RUNNING/VERIFYING/INTEGRATING
    - inflight.json exists AND state is not terminal (residual inflight on
      DONE/FAILED tasks does not count as active)
    - active assignment/lease exists AND state is not terminal
    """
    task_dir = bridge_root / "tasks" / task_id
    if not task_dir.is_dir():
        return False
    state = get_state(task_dir).get("state", "")
    if state in _ACTIVE_EXECUTION_STATES:
        return True
    if state in TERMINAL_STATES:
        return False
    if _has_inflight(task_dir):
        return True
    if _has_active_assignment(bridge_root, task_id):
        return True
    return False


def request_task_delete(bridge_root: Path, task_id: str) -> dict:
    """Request deletion of a task record.

    Returns:
        {"deleted": True} — task was physically removed immediately.
        {"deleted": False, "pending": True} — task is active, deferred delete.
        {"error": "..."} — task not found or other error.
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id

    if not task_dir.is_dir():
        return {"error": f"Task not found: {task_id}"}

    marker = task_dir / MARKER_FILE
    marker.touch()

    if is_task_active(bridge_root, task_id):
        logger.info("Deferred delete requested for active task %s", task_id)
        return {"deleted": False, "pending": True}

    finalize_task_delete_if_safe(bridge_root, task_id)
    if not task_dir.exists():
        logger.info("Task %s physically deleted", task_id)
        return {"deleted": True}

    logger.warning("Task %s could not be deleted (became active?)", task_id)
    return {"deleted": False, "pending": True}


def finalize_task_delete_if_safe(bridge_root: Path, task_id: str) -> bool:
    """Physically remove a deferred-delete task if it is no longer active.

    Returns True if the task was removed, False otherwise.
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id

    if not task_dir.is_dir():
        return False
    if not is_delete_requested(task_dir):
        return False
    if is_task_active(bridge_root, task_id):
        return False

    try:
        shutil.rmtree(task_dir)
    except Exception as exc:
        logger.warning("Failed to remove task dir %s: %s", task_id, exc)
        return False

    assignment_dir = bridge_root / "runtime" / "assignments" / task_id
    if assignment_dir.is_dir():
        try:
            shutil.rmtree(assignment_dir)
        except Exception:
            pass

    logger.info("Deferred delete finalized for task %s", task_id)
    return True


def finalize_pending_deletes(bridge_root: Path) -> int:
    """Scan all tasks with delete markers and finalize those that are safe.

    Called from existing lifecycle points (auto_dispatch reconcile, worker
    finally). Not a new daemon.
    """
    bridge_root = Path(bridge_root)
    tasks_dir = bridge_root / "tasks"
    if not tasks_dir.exists():
        return 0
    count = 0
    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        if not is_delete_requested(task_dir):
            continue
        if finalize_task_delete_if_safe(bridge_root, task_dir.name):
            count += 1
    return count