# AI生成
"""Capacity planning for scheduler."""

from __future__ import annotations

from ..core.models import Worker, Assignment


def get_active_assignments(assignments: list[Assignment], worker_id: str) -> list[Assignment]:
    """Get active (non-finished) assignments for a worker."""
    return [
        a for a in assignments
        if a.worker_id == worker_id and a.finished_at is None
    ]


def has_capacity(worker: Worker, assignments: list[Assignment]) -> bool:
    """Check if worker has available capacity for a new assignment."""
    active = get_active_assignments(assignments, worker.id)
    return len(active) < worker.concurrency_limit


def available_capacity(worker: Worker, assignments: list[Assignment]) -> int:
    """Return remaining capacity slots for a worker."""
    active = get_active_assignments(assignments, worker.id)
    return max(0, worker.concurrency_limit - len(active))


def filter_with_capacity(
    workers: list[Worker],
    assignments: list[Assignment],
) -> list[Worker]:
    """Filter workers that have available capacity."""
    return [w for w in workers if has_capacity(w, assignments)]
