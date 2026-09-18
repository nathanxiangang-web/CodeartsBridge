# AI生成
"""Main scheduler planner.

Orchestrates: dependency → role/skill match → capacity → anti-affinity → score → assign.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..core.models import (
    Task, Worker, Assignment, ExecutionPlan,
    WorkersRegistry, Registry,
)
from ..core.ids import generate_assignment_id
from ..core.state import READY, QUEUED, DONE, CANCELLED, get_state
from ..atomic import atomic_write_json, read_json_or_none

from .matcher import filter_candidates, score_worker
from .dependency import is_dependency_ready, get_blocked_dependencies
from .capacity import filter_with_capacity, has_capacity
from .affinity import apply_anti_affinity, apply_preferred, get_excluded_workers
from .lease import get_active_lease, create_lease, release_lease, is_expired


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def select_plan(
    tasks: list[Task],
    workers: list[Worker],
    existing_assignments: list[Assignment],
    tasks_root: Path,
    leases_dir: Path,
    max_workers: int = 4,
) -> ExecutionPlan:
    """Select a dispatch plan for candidate tasks.

    For each task in candidate state (READY/FIX_REQUIRED/RETRYABLE):
    1. Check dependencies are satisfied
    2. Check no active lease exists
    3. Filter workers by role + skill match
    4. Filter by capacity
    5. Apply anti-affinity (exclude implementer from review)
    6. Score and pick best worker
    7. Create Assignment
    """
    plan = ExecutionPlan()
    used_workers: set[str] = set()

    # Sort tasks by priority (higher first)
    sorted_tasks = sorted(tasks, key=lambda t: -t.priority)

    for task in sorted_tasks:
        if len(plan.assignments) >= max_workers:
            break

        # Check dependencies
        if not is_dependency_ready(task.depends_on, tasks_root):
            blocked = get_blocked_dependencies(task.depends_on, tasks_root)
            plan.skipped.append({
                "taskId": task.task_id,
                "reason": "dependencies_not_ready",
                "blocked": blocked,
            })
            continue

        # Check no active lease
        active_lease = get_active_lease(leases_dir, task.task_id)
        if active_lease is not None:
            plan.skipped.append({
                "taskId": task.task_id,
                "reason": "active_lease",
                "leaseId": active_lease.lease_id,
            })
            continue

        # Filter candidates by role + skill
        candidates = filter_candidates(workers, task)
        if not candidates:
            plan.skipped.append({
                "taskId": task.task_id,
                "reason": "no_matching_worker",
            })
            continue

        # An explicit META.workerId is a hard routing constraint.
        # It must never silently fall back to another worker. Role/skill
        # validation above and capacity/anti-affinity validation below still apply.
        if task.worker_id:
            candidates = [w for w in candidates if w.id == task.worker_id]
            if not candidates:
                plan.skipped.append({
                    "taskId": task.task_id,
                    "reason": "explicit_worker_unavailable",
                    "workerId": task.worker_id,
                })
                continue

        # Filter by capacity
        candidates = filter_with_capacity(candidates, existing_assignments + plan.assignments)
        if not candidates:
            plan.skipped.append({
                "taskId": task.task_id,
                "reason": "no_capacity",
            })
            continue

        # Apply anti-affinity
        candidates = apply_anti_affinity(candidates, task, existing_assignments)
        if not candidates:
            # Fallback: if anti-affinity removes all and no fallback allowed
            plan.skipped.append({
                "taskId": task.task_id,
                "reason": "anti_affinity_excluded_all",
            })
            continue

        # Sort by score (preferred worker first, then by score)
        candidates = apply_preferred(candidates, task)
        candidates.sort(key=lambda w: -score_worker(w, task))

        # Pick best worker
        chosen = candidates[0]

        # Create assignment
        assignment = Assignment(
            assignment_id=generate_assignment_id(),
            task_id=task.task_id,
            worker_id=chosen.id,
            role=task.role,
            attempt=1,
            created_at=_now_iso(),
        )

        # Create lease
        lease = create_lease(
            leases_dir,
            task.task_id,
            chosen.id,
            ttl_minutes=task.execution.hard_timeout_minutes,
        )
        assignment.lease_id = lease.lease_id

        plan.assignments.append(assignment)
        used_workers.add(chosen.id)

    return plan


def save_assignment(assignments_dir: Path, assignment: Assignment) -> None:
    """Persist an assignment to disk."""
    assignments_dir = Path(assignments_dir)
    assignments_dir.mkdir(parents=True, exist_ok=True)
    path = assignments_dir / f"{assignment.assignment_id}.json"
    atomic_write_json(path, assignment.to_dict())


def finish_assignment(
    assignments_dir: Path,
    leases_dir: Path,
    task_id: str,
    *,
    finished_at: str | None = None,
) -> int:
    """Mark unfinished assignments for a task complete and release their leases."""
    assignments_dir = Path(assignments_dir)
    leases_dir = Path(leases_dir)
    if not assignments_dir.exists():
        return 0

    finished = finished_at or _now_iso()
    count = 0
    for path in assignments_dir.glob("*.json"):
        data = read_json_or_none(path)
        if not data or data.get("taskId") != task_id or data.get("finishedAt"):
            continue
        data["finishedAt"] = finished
        atomic_write_json(path, data)
        lease_id = data.get("leaseId")
        if lease_id:
            release_lease(leases_dir, lease_id)
        count += 1
    return count


def reconcile_assignments(
    assignments_dir: Path,
    leases_dir: Path,
    tasks_root: Path,
) -> int:
    """Close stale assignments left behind by crashes, restarts, or terminal tasks."""
    assignments_dir = Path(assignments_dir)
    leases_dir = Path(leases_dir)
    tasks_root = Path(tasks_root)
    if not assignments_dir.exists():
        return 0

    reconciled = 0
    worker_active_states = {"QUEUED", "STARTING", "RUNNING"}

    for path in assignments_dir.glob("*.json"):
        data = read_json_or_none(path)
        if not data or data.get("finishedAt"):
            continue

        task_id = data.get("taskId", "")
        task_state = get_state(tasks_root / task_id).get("state", "") if task_id else ""
        lease_id = data.get("leaseId")
        lease_data = read_json_or_none(leases_dir / f"{lease_id}.json") if lease_id else None
        lease_expired = True
        if lease_data:
            from ..core.models import Lease
            lease_expired = is_expired(Lease.from_dict(lease_data))

        if task_state not in worker_active_states or not lease_data or lease_expired:
            data["finishedAt"] = _now_iso()
            atomic_write_json(path, data)
            if lease_id:
                release_lease(leases_dir, lease_id)
            reconciled += 1

    return reconciled


def load_assignments(assignments_dir: Path) -> list[Assignment]:
    """Load all assignments from disk."""
    assignments_dir = Path(assignments_dir)
    if not assignments_dir.exists():
        return []
    result = []
    for path in assignments_dir.glob("*.json"):
        data = read_json_or_none(path)
        if data is not None:
            result.append(Assignment.from_dict(data))
    return result
