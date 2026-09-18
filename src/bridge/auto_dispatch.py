# AI生成
"""Auto-dispatch engine: automatically dispatches READY tasks to available Workers.

Eliminates manual `bridge dispatch` calls for routine task flow by scanning
tasks/ for candidate-state tasks whose dependencies are all DONE, using the
existing scheduler planner to select tasks and assign workers, then dispatching.

Reuses scheduler.planner.select_plan() for all scheduling decisions:
- dependency resolution
- active-lease idempotency guard
- role/skill matching
- capacity planning
- anti-affinity rules
- worker scoring
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .atomic import read_json_or_none
from .state import (
    get_state, set_state,
    READY, QUEUED, CANCELLED,
    CANDIDATE_STATES,
)
from .core.models import Task, load_registry, load_workers_registry
from .scheduler.planner import (
    select_plan, save_assignment, load_assignments, reconcile_assignments,
)
from .scheduler.lease import release_lease


@dataclass
class AutoDispatchResult:
    """Summary of an auto-dispatch cycle."""
    planned: int = 0
    dispatched: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    assignments: list[dict] = field(default_factory=list)
    skipped_details: list[dict] = field(default_factory=list)
    dry_run: bool = False


def _scan_candidate_tasks(tasks_root: Path) -> list[Task]:
    """Scan tasks/ for tasks in candidate states (READY/FIX_REQUIRED/RETRYABLE).

    Returns Task objects sorted by task_id for deterministic ordering.
    """
    tasks: list[Task] = []
    if not tasks_root.exists():
        return tasks
    for task_dir in sorted(tasks_root.iterdir()):
        if not task_dir.is_dir():
            continue
        state = get_state(task_dir)
        status = state.get("status") or state.get("state", "")
        if status not in CANDIDATE_STATES:
            continue
        meta = read_json_or_none(task_dir / "META.json")
        if meta is None:
            continue
        try:
            task = Task.from_dict(meta)
            tasks.append(task)
        except (KeyError, TypeError):
            continue
    return tasks


def auto_dispatch(
    bridge_root: Path,
    max_workers: int = 4,
    dry_run: bool = False,
) -> AutoDispatchResult:
    """Auto-dispatch candidate tasks to available workers.

    Steps:
    1. Scan tasks/ for candidate-state tasks (READY/FIX_REQUIRED/RETRYABLE)
    2. Load enabled workers from workers.json
    3. Use scheduler.planner.select_plan() to plan assignments
       (planner handles dependency check, lease guard, capacity, affinity, scoring)
    4. For each planned assignment:
       - Save assignment to disk
       - Transition state READY -> QUEUED
       - Spawn worker process (unless dry_run)
    5. Return summary

    Idempotency: select_plan checks for active leases before dispatching,
    so calling auto_dispatch twice will not double-dispatch.

    Args:
        bridge_root: Path to the bridge root directory.
        max_workers: Maximum number of concurrent assignments to plan.
        dry_run: If True, show what would be dispatched without dispatching.

    Returns:
        AutoDispatchResult with planned, dispatched, skipped, errors counts.
    """
    bridge_root = Path(bridge_root)
    tasks_root = bridge_root / "tasks"
    leases_dir = bridge_root / "runtime" / "leases"
    assignments_dir = bridge_root / "runtime" / "assignments"
    assignments_dir.mkdir(parents=True, exist_ok=True)

    result = AutoDispatchResult(dry_run=dry_run)

    # Scan candidate tasks
    candidate_tasks = _scan_candidate_tasks(tasks_root)
    if not candidate_tasks:
        return result

    # Load project registry. Project placement is required for safe scheduling.
    projects_path = bridge_root / "projects.json"
    if not projects_path.is_file():
        result.errors.append("projects.json not found")
        return result
    registry = load_registry(projects_path)

    # Load workers
    workers_path = bridge_root / "workers.json"
    if not workers_path.is_file():
        result.errors.append("workers.json not found")
        return result
    workers_reg = load_workers_registry(workers_path)
    workers = workers_reg.enabled_workers()
    if not workers:
        result.errors.append("no enabled workers")
        return result

    # Reconcile stale runtime records before capacity tracking.
    # This prevents completed/crashed tasks from permanently consuming worker slots.
    reconcile_assignments(assignments_dir, leases_dir, tasks_root)
    existing_assignments = load_assignments(assignments_dir)

    # Plan via scheduler (select_plan handles deps, leases, capacity, affinity, scoring)
    plan = select_plan(
        tasks=candidate_tasks,
        workers=workers,
        existing_assignments=existing_assignments,
        tasks_root=tasks_root,
        leases_dir=leases_dir,
        max_workers=max_workers,
        registry=registry,
    )

    result.planned = len(plan.assignments)
    result.skipped = len(plan.skipped)
    result.skipped_details = list(plan.skipped)

    # Dry run: release leases created by planner, return plan summary
    if dry_run:
        for assignment in plan.assignments:
            if assignment.lease_id:
                release_lease(leases_dir, assignment.lease_id)
            result.assignments.append({
                "taskId": assignment.task_id,
                "workerId": assignment.worker_id,
                "role": assignment.role,
            })
        return result

    # Execute dispatch
    for assignment in plan.assignments:
        task_dir = tasks_root / assignment.task_id

        # Race protection: skip if no longer candidate
        current = get_state(task_dir)
        current_status = current.get("status") or current.get("state", "")
        if current_status not in CANDIDATE_STATES:
            result.skipped += 1
            result.errors.append(
                f"{assignment.task_id}: no longer candidate ({current_status})"
            )
            if assignment.lease_id:
                release_lease(leases_dir, assignment.lease_id)
            continue

        # Save assignment
        save_assignment(assignments_dir, assignment)

        # Transition state READY -> QUEUED
        set_state(
            task_dir, QUEUED,
            message=f"auto-dispatched to {assignment.worker_id}",
            assigned_worker_id=assignment.worker_id,
        )

        # Spawn worker process
        try:
            subprocess.Popen(
                [sys.executable, "-m", "bridge.cli", "run", "-t", assignment.task_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            result.dispatched += 1
            result.assignments.append({
                "taskId": assignment.task_id,
                "workerId": assignment.worker_id,
                "role": assignment.role,
            })
        except Exception as e:
            # Spawn failed: revert to READY, release lease
            set_state(
                task_dir, READY,
                message=f"spawn failed: {e}",
                assigned_worker_id="",
            )
            if assignment.lease_id:
                release_lease(leases_dir, assignment.lease_id)
            result.errors.append(f"{assignment.task_id}: spawn failed: {e}")

    return result
