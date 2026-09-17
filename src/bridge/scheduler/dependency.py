# AI生成
"""Dependency resolution for scheduler."""

from __future__ import annotations

from pathlib import Path
import json


def get_task_state(task_dir: Path) -> str | None:
    """Get the current state of a task."""
    state_file = task_dir / "state.json"
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8")).get("state")
    except (json.JSONDecodeError, OSError):
        return None


def is_dependency_ready(depends_on: list[str], tasks_root: Path, done_states: set[str] | None = None) -> bool:
    """Check if all dependencies of a task are satisfied.

    A dependency is satisfied if:
    - The dependency task directory doesn't exist (treated as external/already done)
    - The dependency task is in one of the done_states
    """
    if not depends_on:
        return True

    done_states = done_states or {"DONE", "INTEGRATED", "CANCELLED"}
    tasks_root = Path(tasks_root)

    for dep_id in depends_on:
        dep_dir = tasks_root / dep_id
        if not dep_dir.exists():
            continue  # External dependency, treat as satisfied
        state = get_task_state(dep_dir)
        if state is None:
            return False
        if state not in done_states:
            return False

    return True


def get_blocked_dependencies(depends_on: list[str], tasks_root: Path) -> list[str]:
    """Get list of dependencies that are not yet satisfied."""
    tasks_root = Path(tasks_root)
    blocked = []
    for dep_id in depends_on:
        dep_dir = tasks_root / dep_id
        if not dep_dir.exists():
            continue
        state = get_task_state(dep_dir)
        if state is None or state not in {"DONE", "INTEGRATED", "CANCELLED"}:
            blocked.append(dep_id)
    return blocked
