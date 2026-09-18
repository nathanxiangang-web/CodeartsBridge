# AI生成
"""Priority, estimated duration and critical-path scheduling.

P1-02: Scheduler that considers priority, duration, dependencies, worker capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SchedulingMeta:
    priority: int = 50
    estimated_minutes: float = 0.0
    max_retries: int = 1
    preferred_workers: list[str] = field(default_factory=list)
    resource_class: str = "implementation"

    @classmethod
    def from_meta(cls, meta: dict) -> "SchedulingMeta":
        return cls(
            priority=meta.get("priority", 50),
            estimated_minutes=meta.get("estimatedMinutes", 0.0),
            max_retries=meta.get("maxRetries", 1),
            preferred_workers=meta.get("preferredWorkers", []),
            resource_class=meta.get("resourceClass", "implementation"),
        )


@dataclass
class ScheduledTask:
    task_id: str
    priority: int
    estimated_minutes: float
    attempt: int
    max_retries: int
    preferred_workers: list[str]
    resource_class: str
    dependencies: list[str]
    dependency_states: dict[str, str]

    @property
    def deps_done(self) -> bool:
        return all(s == "DONE" for s in self.dependency_states.values())

    @property
    def deps_pending(self) -> int:
        return sum(1 for s in self.dependency_states.values() if s != "DONE")

    @property
    def can_retry(self) -> bool:
        return self.attempt <= self.max_retries

    @property
    def scheduling_score(self) -> float:
        """Higher score = higher priority for scheduling.

        Considers: priority, deps_pending (fewer = better), estimated_minutes (shorter = better for throughput).
        """
        score = float(self.priority)
        score -= self.deps_pending * 100  # Tasks with pending deps go last
        if self.estimated_minutes > 0:
            score += 10.0 / self.estimated_minutes  # Short tasks get slight boost
        return score


def build_scheduled_task(
    task_id: str,
    meta: dict,
    attempt: int,
    dependencies: list[str],
    dependency_states: dict[str, str],
) -> ScheduledTask:
    sm = SchedulingMeta.from_meta(meta)
    return ScheduledTask(
        task_id=task_id,
        priority=sm.priority,
        estimated_minutes=sm.estimated_minutes,
        attempt=attempt,
        max_retries=sm.max_retries,
        preferred_workers=sm.preferred_workers,
        resource_class=sm.resource_class,
        dependencies=dependencies,
        dependency_states=dependency_states,
    )


def sort_by_critical_path(tasks: list[ScheduledTask]) -> list[ScheduledTask]:
    """Sort tasks by critical path: deps done first, then by scheduling score."""
    ready = [t for t in tasks if t.deps_done and t.can_retry]
    blocked = [t for t in tasks if not t.deps_done]
    exhausted = [t for t in tasks if t.deps_done and not t.can_retry]

    ready.sort(key=lambda t: -t.scheduling_score)
    blocked.sort(key=lambda t: -t.scheduling_score)

    return ready + blocked + exhausted


def select_worker(
    task: ScheduledTask,
    available_workers: list[Any],
    worker_usage: dict[str, int],
) -> Any | None:
    """Select best worker for a task.

    Considers: preferred_workers, worker capability, worker availability, concurrency.
    """
    # Try preferred workers first
    for wid in task.preferred_workers:
        for w in available_workers:
            if w.id != wid:
                continue
            if not getattr(w, "enabled", True):
                continue
            if worker_usage.get(w.id, 0) >= getattr(w, "concurrency_limit", 1):
                continue
            caps = getattr(w, "capabilities", [])
            if caps and task.resource_class not in caps:
                continue
            return w

    # Fall back to any available worker with matching capability
    for w in sorted(available_workers, key=lambda x: x.id):
        if not getattr(w, "enabled", True):
            continue
        if worker_usage.get(w.id, 0) >= getattr(w, "concurrency_limit", 1):
            continue
        caps = getattr(w, "capabilities", [])
        if caps and task.resource_class not in caps:
            continue
        return w

    return None


def plan_dispatch(
    tasks: list[ScheduledTask],
    available_workers: list[Any],
    worker_usage: dict[str, int],
) -> list[tuple[str, Any]]:
    """Plan dispatch: return list of (task_id, worker) pairs.

    Only schedules tasks whose deps are done and can retry.
    Respects worker concurrency limits.
    """
    sorted_tasks = sort_by_critical_path(tasks)
    usage = dict(worker_usage)
    plan = []

    for task in sorted_tasks:
        if not task.deps_done or not task.can_retry:
            continue
        worker = select_worker(task, available_workers, usage)
        if worker is None:
            continue
        plan.append((task.task_id, worker))
        usage[worker.id] = usage.get(worker.id, 0) + 1

    return plan