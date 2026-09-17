# AI生成
"""AssignmentService — manage task-to-worker assignments.

Phase 8: Application Layer service for assignments.
"""
from __future__ import annotations

import json
from pathlib import Path


def list_assignments(bridge_root: str | Path) -> list[dict]:
    """List all assignments."""
    af = Path(bridge_root) / "assignments.json"
    if not af.exists():
        return []
    data = json.loads(af.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.values())
    return data


def get_assignment(bridge_root: str | Path, assignment_id: str) -> dict | None:
    """Get a single assignment by ID."""
    for a in list_assignments(bridge_root):
        if a.get("assignmentId") == assignment_id:
            return a
    return None


def save_assignment(bridge_root: str | Path, assignment: dict) -> dict:
    """Save or update an assignment."""
    bridge_root = Path(bridge_root)
    af = bridge_root / "assignments.json"
    assignments = list_assignments(bridge_root)
    # Replace if exists, else append
    found = False
    for i, a in enumerate(assignments):
        if a.get("assignmentId") == assignment.get("assignmentId"):
            assignments[i] = assignment
            found = True
            break
    if not found:
        assignments.append(assignment)
    af.write_text(json.dumps(assignments, indent=2, ensure_ascii=False), encoding="utf-8")
    return assignment


def get_active_assignments_for_worker(bridge_root: str | Path, worker_id: str) -> list[dict]:
    """Get active (non-completed) assignments for a worker."""
    return [
        a for a in list_assignments(bridge_root)
        if a.get("workerId") == worker_id and a.get("status", "active") == "active"
    ]


def get_assignment_count_for_worker(bridge_root: str | Path, worker_id: str) -> int:
    """Count active assignments for a worker."""
    return len(get_active_assignments_for_worker(bridge_root, worker_id))