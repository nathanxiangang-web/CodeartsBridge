# AI生成
"""Dispatch service: orchestrate task dispatch using the scheduler.

Application-layer service that connects the scheduler planner with
the runtime supervisor and agent adapters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..atomic import read_json_or_none
from ..core.state import get_state, set_state, CREATED, READY, QUEUED, CANCELLED
from ..core.models import load_registry, load_workers_registry
from ..scheduler.planner import select_plan, save_assignment
from ..scheduler.lease import create_lease, get_expired_leases, release_lease
from ..scheduler.affinity import get_excluded_workers

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    planned: int = 0
    dispatched: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    assignments: list[dict] = field(default_factory=list)


def dispatch_tasks(
    bridge_root: Path,
    max_workers: int = 4,
    dry_run: bool = False,
) -> DispatchResult:
    """Dispatch ready tasks to available workers."""
    bridge_root = Path(bridge_root)
    result = DispatchResult()

    # Load registries
    registry = load_registry(bridge_root / "projects.json")
    workers = load_workers_registry(bridge_root / "workers.json")

    # Find ready tasks
    tasks_dir = bridge_root / "tasks"
    if not tasks_dir.exists():
        return result

    ready_tasks = []
    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        task_id = task_dir.name
        state = get_state(task_dir).get("state", CREATED)
        if state == READY:
            meta = read_json_or_none(task_dir / "META.json")
            if meta:
                ready_tasks.append(meta)

    if not ready_tasks:
        return result

    # Release expired leases
    expired = get_expired_leases(bridge_root / "runtime")
    for lease in expired:
        release_lease(bridge_root / "runtime", lease.lease_id)

    # Plan dispatch
    plan = select_plan(
        ready_tasks=ready_tasks,
        workers=workers,
        registry=registry,
        bridge_root=bridge_root,
        max_workers=max_workers,
    )

    result.planned = len(plan)

    if dry_run:
        return result

    # Execute plan
    for assignment in plan:
        task_id = assignment.get("taskId", "")
        worker_id = assignment.get("workerId", "")

        # Check if task was cancelled while waiting
        task_dir = tasks_dir / task_id
        if get_state(task_dir).get("state", CREATED) == CANCELLED:
            result.skipped += 1
            continue

        # Create lease
        lease = create_lease(
            bridge_root / "runtime",
            task_id=task_id,
            worker_id=worker_id,
            ttl_minutes=30,
        )

        # Save assignment
        save_assignment(bridge_root, assignment)

        # Transition state
        set_state(task_dir, QUEUED)

        result.dispatched += 1
        result.assignments.append(assignment)

    return result
