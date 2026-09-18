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


def collect_worker_stats(
    bridge_root: Path,
    *,
    role: str | None = None,
    project_id: str | None = None,
) -> dict[str, WorkerPerformance]:
    """Compute per-worker performance, optionally scoped to role/project.

    Runtime-assigned worker identity comes from telemetry.TaskMetrics. Filtering
    keeps adaptive routing from treating performance in one role/project as
    evidence for an unrelated workload.
    """
    bridge_root = Path(bridge_root)
    tasks_dir = bridge_root / "tasks"
    metrics = collect_all_metrics(tasks_dir)

    by_worker: dict[str, list[TaskMetrics]] = {}
    for m in metrics:
        if not m.worker_id or m.execution_time_seconds is None:
            continue
        if role is not None and m.role != role:
            continue
        if project_id is not None:
            task_meta = read_json_or_none(tasks_dir / m.task_id / "META.json") or {}
            if task_meta.get("projectId", "") != project_id:
                continue
        by_worker.setdefault(m.worker_id, []).append(m)

    result: dict[str, WorkerPerformance] = {}
    now = _now_iso()

    for worker_id, worker_metrics in by_worker.items():
        task_count = len(worker_metrics)
        success_count = sum(1 for m in worker_metrics if m.status == DONE)
        durations = [
            m.execution_time_seconds
            for m in worker_metrics
            if m.execution_time_seconds is not None
        ]
        timeout_count = sum(1 for m in worker_metrics if m.is_timeout)
        timestamps = [m.finished_at for m in worker_metrics if m.finished_at]

        result[worker_id] = WorkerPerformance(
            worker_id=worker_id,
            task_count=task_count,
            success_rate=success_count / task_count if task_count else 0.0,
            avg_duration=sum(durations) / len(durations) if durations else 0.0,
            timeout_rate=timeout_count / task_count if task_count else 0.0,
            last_updated=max(timestamps) if timestamps else now,
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
    """Recommend a worker using workload-relevant historical performance.

    Evidence priority:
    1. same role + same project
    2. same role across projects
    3. no recommendation (fall back to the static scheduler)

    We intentionally do not fall back to global cross-role history: a worker
    being fast at tests or reviews is not evidence that it should be preferred
    for implementation work.
    """
    bridge_root = Path(bridge_root)
    meta = _read_task_meta(bridge_root, task_id)
    if meta is None:
        return None

    role = meta.get("role", "implement")
    project_id = meta.get("projectId", "")

    candidate_ids: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, str):
            candidate_ids.append(candidate)
            continue
        candidate_id = getattr(candidate, "id", None)
        if candidate_id:
            candidate_ids.append(candidate_id)

    if not candidate_ids:
        return None

    def _best(stats: dict[str, WorkerPerformance]) -> str | None:
        scored: list[tuple[float, str]] = []
        for worker_id in candidate_ids:
            perf = stats.get(worker_id)
            if perf is None:
                continue
            if perf.task_count < MIN_TASKS_FOR_RECOMMENDATION:
                continue
            if perf.avg_duration <= 0:
                continue
            score = perf.success_rate * (1.0 - perf.timeout_rate) / perf.avg_duration
            scored.append((score, worker_id))
        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][1]

    project_match = _best(
        collect_worker_stats(
            bridge_root,
            role=role,
            project_id=project_id,
        )
    )
    if project_match is not None:
        return project_match

    return _best(collect_worker_stats(bridge_root, role=role))

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
                if enabled_worker_ids:
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
