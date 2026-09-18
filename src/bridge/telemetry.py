"""P1-06: Telemetry and statistics for task throughput, quality and worker utilization.

Collects metrics from state.json + META.json across all tasks and aggregates
them into a report for performance monitoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import read_json_or_none
from .state import (
    get_state, DONE, FAILED, BLOCKED, REVIEW_REQUIRED, FIX_REQUIRED,
    RETRYABLE, CANCELLED, CANCEL_REQUESTED, RUNNING, QUEUED, STARTING,
)


@dataclass
class TaskMetrics:
    """Metrics for a single task extracted from state.json and META.json."""

    task_id: str
    status: str
    attempt: int = 0
    role: str = "implement"
    worker_id: str | None = None
    created_at: str | None = None
    queued_at: str | None = None
    started_at: str | None = None
    running_at: str | None = None
    finished_at: str | None = None
    reviewed_at: str | None = None
    done_at: str | None = None
    tokens: Any = None
    exit_code: int | None = None

    @staticmethod
    def from_task_dir(task_dir: str | Path) -> "TaskMetrics":
        task_dir = Path(task_dir)
        state = get_state(task_dir)
        meta = read_json_or_none(task_dir / "META.json") or {}
        return TaskMetrics(
            task_id=state.get("taskId", task_dir.name),
            status=state.get("status", "UNKNOWN"),
            attempt=int(state.get("attempt", 0)),
            role=meta.get("role", "implement"),
            worker_id=meta.get("workerId"),
            created_at=meta.get("createdAt"),
            queued_at=state.get("queuedAt"),
            started_at=state.get("startedAt"),
            running_at=state.get("runningAt"),
            finished_at=state.get("finishedAt"),
            reviewed_at=state.get("reviewedAt"),
            done_at=state.get("doneAt"),
            tokens=state.get("tokens"),
            exit_code=state.get("exitCode"),
        )

    @staticmethod
    def _parse_ts(ts: str | None) -> datetime | None:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @property
    def queue_time_seconds(self) -> float | None:
        """Time from queued to started (dispatch latency)."""
        q = self._parse_ts(self.queued_at)
        s = self._parse_ts(self.started_at)
        if q and s:
            return (s - q).total_seconds()
        return None

    @property
    def execution_time_seconds(self) -> float | None:
        """Time from started to finished (worker execution)."""
        s = self._parse_ts(self.started_at)
        f = self._parse_ts(self.finished_at)
        if s and f:
            return (f - s).total_seconds()
        return None

    @property
    def review_time_seconds(self) -> float | None:
        """Time from finished to reviewed (review cycle)."""
        f = self._parse_ts(self.finished_at)
        r = self._parse_ts(self.reviewed_at)
        if f and r:
            return (r - f).total_seconds()
        return None

    @property
    def total_cycle_time_seconds(self) -> float | None:
        """Time from created to done (requirement to validated patch)."""
        c = self._parse_ts(self.created_at)
        d = self._parse_ts(self.done_at)
        if c and d:
            return (d - c).total_seconds()
        return None

    @property
    def is_first_pass(self) -> bool:
        """True if task reached REVIEW_REQUIRED or DONE on attempt 1."""
        return self.attempt == 1 and self.status in (REVIEW_REQUIRED, DONE)

    @property
    def is_fix(self) -> bool:
        return self.status == FIX_REQUIRED or self.attempt > 1

    @property
    def is_retry(self) -> bool:
        return self.attempt > 1

    @property
    def is_timeout(self) -> bool:
        return self.exit_code in (124, 137) and self.status in (RUNNING, FAILED)

    @property
    def is_cancelled(self) -> bool:
        return self.status in (CANCELLED, CANCEL_REQUESTED)

    @property
    def is_terminal(self) -> bool:
        return self.status in (DONE, FAILED, BLOCKED, CANCELLED)


@dataclass
class TelemetryReport:
    """Aggregated telemetry report across all tasks."""

    total_tasks: int = 0
    terminal_tasks: int = 0
    first_pass_count: int = 0
    fix_count: int = 0
    retry_count: int = 0
    timeout_count: int = 0
    cancel_count: int = 0
    review_required_count: int = 0
    avg_queue_time_seconds: float | None = None
    avg_execution_time_seconds: float | None = None
    avg_review_time_seconds: float | None = None
    avg_total_cycle_time_seconds: float | None = None
    tasks_per_hour: float | None = None
    total_tokens: int = 0
    first_pass_rate: float = 0.0
    fix_rate: float = 0.0
    retry_rate: float = 0.0
    timeout_rate: float = 0.0
    worker_task_counts: dict[str, int] = field(default_factory=dict)
    role_task_counts: dict[str, int] = field(default_factory=dict)
    window_start: str | None = None
    window_end: str | None = None


def collect_all_metrics(tasks_dir: str | Path) -> list[TaskMetrics]:
    """Collect metrics from all task directories under tasks_dir."""
    tasks_dir = Path(tasks_dir)
    if not tasks_dir.is_dir():
        return []
    metrics = []
    for task_dir in sorted(tasks_dir.iterdir()):
        if task_dir.is_dir() and (task_dir / "state.json").is_file():
            metrics.append(TaskMetrics.from_task_dir(task_dir))
    return metrics


def generate_report(tasks_dir: str | Path) -> TelemetryReport:
    """Generate a telemetry report from all tasks in tasks_dir."""
    metrics = collect_all_metrics(tasks_dir)
    report = TelemetryReport(total_tasks=len(metrics))

    if not metrics:
        return report

    queue_times = []
    exec_times = []
    review_times = []
    cycle_times = []
    timestamps = []

    for m in metrics:
        if m.is_terminal:
            report.terminal_tasks += 1
        if m.is_first_pass:
            report.first_pass_count += 1
        if m.is_fix:
            report.fix_count += 1
        if m.is_retry:
            report.retry_count += 1
        if m.is_timeout:
            report.timeout_count += 1
        if m.is_cancelled:
            report.cancel_count += 1
        if m.status == REVIEW_REQUIRED:
            report.review_required_count += 1

        if m.queue_time_seconds is not None:
            queue_times.append(m.queue_time_seconds)
        if m.execution_time_seconds is not None:
            exec_times.append(m.execution_time_seconds)
        if m.review_time_seconds is not None:
            review_times.append(m.review_time_seconds)
        if m.total_cycle_time_seconds is not None:
            cycle_times.append(m.total_cycle_time_seconds)

        if m.tokens is not None:
            try:
                report.total_tokens += int(m.tokens)
            except (ValueError, TypeError):
                pass

        if m.worker_id:
            report.worker_task_counts[m.worker_id] = report.worker_task_counts.get(m.worker_id, 0) + 1
        report.role_task_counts[m.role] = report.role_task_counts.get(m.role, 0) + 1

        for ts in (m.created_at, m.done_at, m.queued_at):
            if ts:
                timestamps.append(ts)

    def _avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    report.avg_queue_time_seconds = _avg(queue_times)
    report.avg_execution_time_seconds = _avg(exec_times)
    report.avg_review_time_seconds = _avg(review_times)
    report.avg_total_cycle_time_seconds = _avg(cycle_times)

    if timestamps:
        report.window_start = min(timestamps)
        report.window_end = max(timestamps)

    if cycle_times:
        hours = max(sum(cycle_times) / 3600.0, 0.001)
        report.tasks_per_hour = len(cycle_times) / hours

    base = max(report.total_tasks, 1)
    report.first_pass_rate = report.first_pass_count / base
    report.fix_rate = report.fix_count / base
    report.retry_rate = report.retry_count / base
    report.timeout_rate = report.timeout_count / base

    return report


def format_report_text(report: TelemetryReport) -> str:
    """Format a telemetry report as human-readable text."""

    def _fmt_seconds(s: float | None) -> str:
        if s is None:
            return "N/A"
        if s < 60:
            return f"{s:.1f}s"
        return f"{s / 60:.1f}m"

    lines = [
        "=== Telemetry Report ===",
        f"Total tasks:         {report.total_tasks}",
        f"Terminal tasks:      {report.terminal_tasks}",
        f"Review required:     {report.review_required_count}",
        "",
        "--- Quality ---",
        f"First pass count:    {report.first_pass_count}",
        f"First pass rate:     {report.first_pass_rate:.1%}",
        f"Fix count:           {report.fix_count}",
        f"Fix rate:            {report.fix_rate:.1%}",
        f"Retry count:         {report.retry_count}",
        f"Retry rate:          {report.retry_rate:.1%}",
        f"Timeout count:       {report.timeout_count}",
        f"Timeout rate:        {report.timeout_rate:.1%}",
        f"Cancel count:        {report.cancel_count}",
        "",
        "--- Timing ---",
        f"Avg queue time:      {_fmt_seconds(report.avg_queue_time_seconds)}",
        f"Avg execution time:  {_fmt_seconds(report.avg_execution_time_seconds)}",
        f"Avg review time:     {_fmt_seconds(report.avg_review_time_seconds)}",
        f"Avg total cycle:     {_fmt_seconds(report.avg_total_cycle_time_seconds)}",
        f"Tasks per hour:      {report.tasks_per_hour:.1f}" if report.tasks_per_hour else "Tasks per hour:      N/A",
        "",
        "--- Resources ---",
        f"Total tokens:        {report.total_tokens}",
    ]

    if report.worker_task_counts:
        lines.append("")
        lines.append("--- Worker Task Counts ---")
        for wid, count in sorted(report.worker_task_counts.items()):
            lines.append(f"  {wid}: {count}")

    if report.role_task_counts:
        lines.append("")
        lines.append("--- Role Task Counts ---")
        for role, count in sorted(report.role_task_counts.items()):
            lines.append(f"  {role}: {count}")

    if report.window_start and report.window_end:
        lines.append("")
        lines.append("--- Window ---")
        lines.append(f"  Start: {report.window_start}")
        lines.append(f"  End:   {report.window_end}")

    return "\n".join(lines)


def generate_report_text(tasks_dir: str | Path) -> str:
    """Convenience: generate and format a report in one call."""
    return format_report_text(generate_report(tasks_dir))