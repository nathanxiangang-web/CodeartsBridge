"""P3-01: Adaptive scheduling strategy.

Uses historical telemetry data to automatically adjust scheduling parameters:
worker selection, priority weighting, and timeout estimation.

Reuses telemetry.py for metrics collection and scheduler package for planning.
Pure statistics only (mean, stddev, rate) - no ML libraries.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import read_json_or_none, atomic_write_json
from .auto_dispatch import auto_dispatch, AutoDispatchResult
from .state import get_state, DONE, CANDIDATE_STATES
from .telemetry import TaskMetrics, collect_all_metrics


DEFAULT_TIMEOUT_MINUTES: float = 15.0
MIN_TASKS_FOR_RECOMMENDATION: int = 3
_TIMEOUT_MIN_MINUTES: float = 1.0
_TIMEOUT_MAX_MINUTES: float = 60.0


@dataclass
class WorkerPerformance:
    """Per-worker performance metrics computed from historical telemetry."""

    worker_id: str
    task_count: int = 0
    success_rate: float = 0.0
    avg_duration: float = 0.0
    timeout_rate: float = 0.0
    last_updated: str = ""


def _stddev(values: list[float]) -> float:
    """Population standard deviation. Returns 0.0 for empty input."""
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_worker_stats(bridge_root: Path) -> dict[str, WorkerPerformance]:
    """Scan completed tasks and compute per-worker performance stats.

    A task contributes to a worker's stats when it has a worker_id in META.json
    and a measurable execution_time_seconds (started_at -> finished_at).

    success_rate   = count(status == DONE) / task_count
    avg_duration   = mean(execution_time_seconds) in seconds
    timeout_rate   = count(is_timeout) / task_count

    Returns a dict mapping worker_id -> WorkerPerformance. Workers with no
    measurable tasks are omitted.
    """
    bridge_root = Path(bridge_root)
    tasks_dir = bridge_root / "tasks"
    metrics = collect_all_metrics(tasks_dir)

    by_worker: dict[str, list[TaskMetrics]] = {}
    for m in metrics:
        if not m.worker_id:
            continue
        if m.execution_time_seconds is None:
            continue
        by_worker.setdefault(m.worker_id, []).append(m)

    result: dict[str, WorkerPerformance] = {}
    now = _now_iso()

    for worker_id, worker_metrics in by_worker.items():
        task_count = len(worker_metrics)
        if task_count == 0:
            continue

        success_count = sum(1 for m in worker_metrics if m.status == DONE)
        success_rate = success_count / task_count

        durations = [
            m.execution_time_seconds
            for m in worker_metrics
            if m.execution_time_seconds is not None
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        timeout_count = sum(1 for m in worker_metrics if m.is_timeout)
        timeout_rate = timeout_count / task_count

        timestamps = [m.finished_at for m in worker_metrics if m.finished_at]
        last_updated = max(timestamps) if timestamps else now

        result[worker_id] = WorkerPerformance(
            worker_id=worker_id,
            task_count=task_count,
            success_rate=success_rate,
            avg_duration=avg_duration,
            timeout_rate=timeout_rate,
            last_updated=last_updated,
        )

    return result


def _read_task_meta(bridge_root: Path, task_id: str) -> dict | None:
    """Read META.json for a task. Returns None if missing."""
    return read_json_or_none(bridge_root / "tasks" / task_id / "META.json")


def recommend_timeout(task_id: str, bridge_root: Path) -> float:
    """Recommend a timeout (in minutes) for a task based on historical data.

    Strategy:
    - Collect execution durations of tasks sharing the same role and project.
    - recommended_seconds = avg(durations) + 2 * stddev(durations)
    - Convert to minutes and clamp to [1.0, 60.0].
    - Fallback to DEFAULT_TIMEOUT_MINUTES when fewer than
      MIN_TASKS_FOR_RECOMMENDATION matching tasks exist.

    Returns timeout in minutes (float).
    """
    bridge_root = Path(bridge_root)
    meta = _read_task_meta(bridge_root, task_id)
    if meta is None:
        return DEFAULT_TIMEOUT_MINUTES

    role = meta.get("role", "implement")
    project_id = meta.get("projectId", "")

    tasks_dir = bridge_root / "tasks"
    all_metrics = collect_all_metrics(tasks_dir)

    matching_durations: list[float] = []
    for m in all_metrics:
        if m.role != role:
            continue
        task_meta = read_json_or_none(bridge_root / "tasks" / m.task_id / "META.json")
        if task_meta is None:
            continue
        if task_meta.get("projectId", "") != project_id:
            continue
        if m.execution_time_seconds is None:
            continue
        matching_durations.append(m.execution_time_seconds)

    if len(matching_durations) < MIN_TASKS_FOR_RECOMMENDATION:
        return DEFAULT_TIMEOUT_MINUTES

    avg = sum(matching_durations) / len(matching_durations)
    sigma = _stddev(matching_durations)
    recommended_seconds = avg + 2.0 * sigma
    recommended_minutes = recommended_seconds / 60.0

    return max(_TIMEOUT_MIN_MINUTES, min(_TIMEOUT_MAX_MINUTES, recommended_minutes))


def recommend_worker(
    task_id: str,
    bridge_root: Path,
    candidates: list,
) -> str | None:
    """Recommend the best worker for a task based on historical performance.

    Score = success_rate * (1 - timeout_rate) / avg_duration

    Only workers with at least MIN_TASKS_FOR_RECOMMENDATION completed tasks
    and a positive avg_duration are scored. Returns None when no candidate
    has sufficient data.

    Args:
        task_id: The task to assign (used for context; currently scoring is
            purely history-based).
        bridge_root: Bridge root path.
        candidates: List of worker IDs (str) or objects with an id
            attribute.

    Returns:
        Best scoring worker ID, or None if data insufficient.
    """
    stats = collect_worker_stats(bridge_root)

    candidate_ids: list[str] = []
    for c in candidates:
        if isinstance(c, str):
            candidate_ids.append(c)
            continue
        cid = getattr(c, "id", None)
        if cid:
            candidate_ids.append(cid)

    scored: list[tuple[float, str]] = []
    for wid in candidate_ids:
        perf = stats.get(wid)
        if perf is None:
            continue
        if perf.task_count < MIN_TASKS_FOR_RECOMMENDATION:
            continue
        if perf.avg_duration <= 0:
            continue
        score = perf.success_rate * (1.0 - perf.timeout_rate) / perf.avg_duration
        scored.append((score, wid))

    if not scored:
        return None

    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def adaptive_dispatch(
    bridge_root: Path,
    max_workers: int = 4,
    dry_run: bool = False,
) -> AutoDispatchResult:
    """Run auto-dispatch with adaptive parameters.

    For each candidate task (READY / FIX_REQUIRED / RETRYABLE):
    1. Compute recommended timeout; if it differs from the current
       hardTimeoutMinutes by more than 1 minute, update META.json.execution
       (hardTimeoutMinutes and softTimeoutMinutes = 80% of hard).
    2. Compute recommended worker from enabled workers; if found and
       different from current preferredWorker, set preferredWorker.
    3. Delegate to auto_dispatch for planning and execution.

    META.json edits are persisted so the scheduler planner sees the adaptive
    values. The edits are idempotent: re-running with stable history leaves
    META.json unchanged.

    Returns the AutoDispatchResult from auto_dispatch.
    """
    from .core.models import load_workers_registry

    bridge_root = Path(bridge_root)
    tasks_root = bridge_root / "tasks"

    enabled_worker_ids: list[str] = []
    workers_path = bridge_root / "workers.json"
    if workers_path.is_file():
        workers_reg = load_workers_registry(workers_path)
        enabled_worker_ids = [w.id for w in workers_reg.enabled_workers()]

    if tasks_root.exists():
        for task_dir in sorted(tasks_root.iterdir()):
            if not task_dir.is_dir():
                continue
            state = get_state(task_dir)
            status = state.get("status") or state.get("state", "")
            if status not in CANDIDATE_STATES:
                continue
            task_id = task_dir.name
            meta = read_json_or_none(task_dir / "META.json")
            if meta is None:
                continue

            changed = False

            try:
                rec_timeout = recommend_timeout(task_id, bridge_root)
                execution = meta.setdefault("execution", {})
                current_hard = execution.get("hardTimeoutMinutes", 15)
                if abs(rec_timeout - float(current_hard)) > 1.0:
                    execution["hardTimeoutMinutes"] = int(round(rec_timeout))
                    execution["softTimeoutMinutes"] = max(
                        1, int(round(rec_timeout * 0.8))
                    )
                    changed = True
            except Exception:
                pass

            try:
                # Explicit workerId is a user/operator routing decision.
                # Adaptive scheduling may tune timeouts, but must not compete
                # with that hard assignment through preferredWorker.
                if enabled_worker_ids and not meta.get("workerId"):
                    rec_worker = recommend_worker(
                        task_id, bridge_root, enabled_worker_ids
                    )
                    if rec_worker is not None:
                        execution = meta.setdefault("execution", {})
                        current_pref = execution.get("preferredWorker")
                        if current_pref != rec_worker:
                            execution["preferredWorker"] = rec_worker
                            changed = True
            except Exception:
                pass

            if changed:
                atomic_write_json(task_dir / "META.json", meta)

    return auto_dispatch(
        bridge_root=bridge_root,
        max_workers=max_workers,
        dry_run=dry_run,
    )
