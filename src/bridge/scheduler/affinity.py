# AI生成
"""Affinity and anti-affinity rules for scheduler.

Key rule (Section 12): The implementer of a task cannot review their own work.
"""

from __future__ import annotations

from ..core.models import Worker, Task, Assignment


def get_excluded_workers(
    task: Task,
    assignments: list[Assignment],
) -> set[str]:
    """Get workers to exclude based on anti-affinity rules.

    - Task's explicit excluded_workers
    - Review anti-affinity: if this is a review task, exclude the implementer
    """
    excluded = set(task.execution.excluded_workers)

    # Review anti-affinity: review task should not go to the implementer
    if task.role == "review" and task.review.independent_worker:
        # Find the implementer assignment for this task's parent
        parent_id = task.parent_task_id or task.task_id
        for a in assignments:
            if a.task_id == parent_id and a.role == "implement":
                excluded.add(a.worker_id)

    return excluded


def apply_anti_affinity(
    workers: list[Worker],
    task: Task,
    assignments: list[Assignment],
) -> list[Worker]:
    """Filter out workers that violate anti-affinity rules."""
    excluded = get_excluded_workers(task, assignments)
    return [w for w in workers if w.id not in excluded]


def apply_preferred(
    workers: list[Worker],
    task: Task,
) -> list[Worker]:
    """Sort workers so preferred worker comes first."""
    preferred = task.execution.preferred_worker
    if not preferred:
        return workers

    preferred_list = [w for w in workers if w.id == preferred]
    rest = [w for w in workers if w.id != preferred]
    return preferred_list + rest
