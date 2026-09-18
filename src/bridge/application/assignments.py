# AI生成
"""AssignmentService — canonical access to scheduler runtime assignments.

Scheduler v2 persists one JSON file per assignment under
runtime/assignments/. A legacy root-level assignments.json is still read for
backward compatibility, but all new writes use the runtime store.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..atomic import atomic_write_json, read_json_or_none


def _runtime_dir(bridge_root: str | Path) -> Path:
    return Path(bridge_root) / "runtime" / "assignments"


def _legacy_assignments(bridge_root: str | Path) -> list[dict]:
    af = Path(bridge_root) / "assignments.json"
    if not af.exists():
        return []
    try:
        data = json.loads(af.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = list(data.values())
    return data if isinstance(data, list) else []


def list_assignments(bridge_root: str | Path) -> list[dict]:
    """List canonical runtime assignments plus non-duplicated legacy records."""
    runtime_dir = _runtime_dir(bridge_root)
    assignments: list[dict] = []
    seen: set[str] = set()

    if runtime_dir.exists():
        for path in sorted(runtime_dir.glob("*.json")):
            data = read_json_or_none(path)
            if not isinstance(data, dict):
                continue
            assignment_id = str(data.get("assignmentId") or path.stem)
            data.setdefault("assignmentId", assignment_id)
            assignments.append(data)
            seen.add(assignment_id)

    for legacy in _legacy_assignments(bridge_root):
        assignment_id = str(legacy.get("assignmentId") or "")
        if assignment_id and assignment_id in seen:
            continue
        assignments.append(legacy)
        if assignment_id:
            seen.add(assignment_id)

    return assignments


def get_assignment(bridge_root: str | Path, assignment_id: str) -> dict | None:
    """Get a single assignment by ID."""
    for assignment in list_assignments(bridge_root):
        if assignment.get("assignmentId") == assignment_id:
            return assignment
    return None


def save_assignment(bridge_root: str | Path, assignment: dict) -> dict:
    """Save/update an assignment in the canonical runtime store."""
    assignment_id = str(assignment.get("assignmentId") or "").strip()
    if not assignment_id:
        raise ValueError("assignmentId required")

    runtime_dir = _runtime_dir(bridge_root)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / f"{assignment_id}.json"
    atomic_write_json(path, assignment)
    return assignment


def _is_active(assignment: dict) -> bool:
    """Support v2 finishedAt semantics and legacy status semantics."""
    if "finishedAt" in assignment:
        return not bool(assignment.get("finishedAt"))
    return assignment.get("status", "active") == "active"


def get_active_assignments_for_worker(
    bridge_root: str | Path,
    worker_id: str,
) -> list[dict]:
    """Get unfinished assignments for a worker."""
    return [
        assignment
        for assignment in list_assignments(bridge_root)
        if assignment.get("workerId") == worker_id and _is_active(assignment)
    ]


def get_assignment_count_for_worker(bridge_root: str | Path, worker_id: str) -> int:
    """Count active assignments for a worker."""
    return len(get_active_assignments_for_worker(bridge_root, worker_id))
