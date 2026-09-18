# AI生成
"""Dispatch service aligned with the canonical scheduler runtime contract."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..atomic import read_json_or_none
from ..core.models import Task, load_workers_registry
from ..core.state import get_state, set_state, READY, QUEUED
from ..scheduler.planner import (
    select_plan,
    save_assignment,
    load_assignments,
    reconcile_assignments,
)
from ..scheduler.lease import release_lease

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    planned: int = 0
    dispatched: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    assignments: list[dict] = field(default_factory=list)
    skipped_details: list[dict] = field(default_factory=list)
    dry_run: bool = False


def dispatch_tasks(
    bridge_root: Path,
    max_workers: int = 4,
    dry_run: bool = False,
) -> DispatchResult:
    """Plan and queue READY tasks using the same scheduler store as auto-dispatch.

    This application-layer entry point intentionally does not spawn worker
    processes. It owns deterministic planning/persistence/state transition only.
    """
    bridge_root = Path(bridge_root)
    result = DispatchResult(dry_run=dry_run)

    tasks_root = bridge_root / "tasks"
    assignments_dir = bridge_root / "runtime" / "assignments"
    leases_dir = bridge_root / "runtime" / "leases"
    assignments_dir.mkdir(parents=True, exist_ok=True)

    if not tasks_root.exists():
        return result

    workers_path = bridge_root / "workers.json"
    if not workers_path.is_file():
        result.errors.append("workers.json not found")
        return result

    workers = load_workers_registry(workers_path).enabled_workers()
    if not workers:
        result.errors.append("no enabled workers")
        return result

    ready_tasks: list[Task] = []
    for task_dir in sorted(tasks_root.iterdir()):
        if not task_dir.is_dir():
            continue
        state = get_state(task_dir).get("state", "")
        if state != READY:
            continue
        meta = read_json_or_none(task_dir / "META.json")
        if not isinstance(meta, dict):
            continue
        try:
            ready_tasks.append(Task.from_dict(meta))
        except (KeyError, TypeError, ValueError) as exc:
            result.errors.append(f"{task_dir.name}: invalid META: {exc}")

    if not ready_tasks:
        return result

    reconcile_assignments(assignments_dir, leases_dir, tasks_root)
    existing_assignments = load_assignments(assignments_dir)

    plan = select_plan(
        tasks=ready_tasks,
        workers=workers,
        existing_assignments=existing_assignments,
        tasks_root=tasks_root,
        leases_dir=leases_dir,
        max_workers=max_workers,
    )

    result.planned = len(plan.assignments)
    result.skipped = len(plan.skipped)
    result.skipped_details = list(plan.skipped)

    if dry_run:
        for assignment in plan.assignments:
            if assignment.lease_id:
                release_lease(leases_dir, assignment.lease_id)
            result.assignments.append(assignment.to_dict())
        return result

    for assignment in plan.assignments:
        task_dir = tasks_root / assignment.task_id
        if get_state(task_dir).get("state", "") != READY:
            result.skipped += 1
            result.errors.append(
                f"{assignment.task_id}: no longer READY"
            )
            if assignment.lease_id:
                release_lease(leases_dir, assignment.lease_id)
            continue

        save_assignment(assignments_dir, assignment)
        set_state(
            task_dir,
            QUEUED,
            assignedWorkerId=assignment.worker_id,
        )
        result.dispatched += 1
        result.assignments.append(assignment.to_dict())

    return result
