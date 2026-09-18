"""P1-06 / P3-01: trustworthy telemetry for task throughput and quality.

P3-01 tightens metric semantics so later data-driven scheduling does not learn
from misleading denominators or summed task durations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .atomic import read_json_or_none
from .state import (
    get_state, DONE, FAILED, BLOCKED, REVIEW_REQUIRED, FIX_REQUIRED,
    RETRYABLE, CANCELLED, CANCEL_REQUESTED, RUNNING, QUEUED, STARTING,
    INTEGRATION_FAILED,
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
            status=state.get("status", state.get("state", "UNKNOWN")),
            attempt=int(state.get("attempt", 0)),
            role=meta.get("role", "implement"),
            worker_id=state.get("assignedWorkerId") or meta.get("workerId"),
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
        """Time from queued to process start."""
        queued = self._parse_ts(self.queued_at)
        started = self._parse_ts(self.started_at)
        if queued and started:
            return max(0.0, (started - queued).total_seconds())
        return None

    @property
    def execution_time_seconds(self) -> float | None:
        """Worker busy time from start/running to review-ready/terminal completion."""
        started = self._parse_ts(self.running_at) or self._parse_ts(self.started_at)
        finished = self._parse_ts(self.finished_at) or self._parse_ts(self.done_at)
        if started and finished:
            return max(0.0, (finished - started).total_seconds())
        return None

    @property
    def review_time_seconds(self) -> float | None:
        """Time from worker finish to explicit review/fix decision."""
        finished = self._parse_ts(self.finished_at)
        reviewed = self._parse_ts(self.reviewed_at) or self._parse_ts(self.done_at)
        if finished and reviewed:
            return max(0.0, (reviewed - finished).total_seconds())
        return None

    @property
    def total_cycle_time_seconds(self) -> float | None:
        """Wall-clock time from task creation to DONE."""
        created = self._parse_ts(self.created_at)
        done = self._parse_ts(self.done_at)
        if created and done:
            return max(0.0, (done - created).total_seconds())
        return None

    @property
    def is_evaluated(self) -> bool:
        """Task has produced a reviewable outcome at least once."""
        return (
            self.finished_at is not None
            or self.status in (REVIEW_REQUIRED, FIX_REQUIRED, DONE)
            or self.attempt > 1
        )

    @property
    def is_executed(self) -> bool:
        return self.started_at is not None or self.running_at is not None

    @property
    def is_completed(self) -> bool:
        return self.status == DONE and self.done_at is not None

    @property
    def is_first_pass(self) -> bool:
        """Task is currently accepted/review-ready without a retry/fix attempt."""
        return self.attempt <= 1 and self.status in (REVIEW_REQUIRED, DONE)

    @property
    def is_fix(self) -> bool:
        return self.status == FIX_REQUIRED or self.attempt > 1

    @property
    def is_retry(self) -> bool:
        return self.attempt > 1

    @property
    def is_timeout(self) -> bool:
        return self.exit_code in (124, 137) and self.is_executed

    @property
    def is_cancelled(self) -> bool:
        return self.status in (CANCELLED, CANCEL_REQUESTED)

    @property
    def is_terminal(self) -> bool:
        return self.status in (DONE, FAILED, BLOCKED, CANCELLED, INTEGRATION_FAILED)


@dataclass
class TelemetryReport:
    """Aggregated telemetry report with explicit metric denominators."""

    total_tasks: int = 0
    terminal_tasks: int = 0
    evaluated_tasks: int = 0
    executed_tasks: int = 0
    completed_tasks: int = 0
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
    worker_utilization: dict[str, float] = field(default_factory=dict)
    avg_worker_utilization: float | None = None
    role_task_counts: dict[str, int] = field(default_factory=dict)

    window_start: str | None = None
    window_end: str | None = None
    execution_window_start: str | None = None
    execution_window_end: str | None = None


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


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _token_total(value: Any) -> int:
    """Accept scalar tokens and common structured token payloads."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        for key in ("total", "total_tokens", "totalTokens"):
            if key in value:
                try:
                    return int(value[key])
                except (TypeError, ValueError):
                    return 0
        total = 0
        for key in ("input", "output", "input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
            try:
                total += int(value.get(key, 0) or 0)
            except (TypeError, ValueError):
                pass
        return total
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def generate_report(tasks_dir: str | Path) -> TelemetryReport:
    """Generate a semantically stable telemetry report from task history.

    Denominators:
    - first_pass_rate / fix_rate: tasks that reached a reviewable outcome.
    - retry_rate / timeout_rate: tasks that actually started execution.
    - tasks_per_hour: DONE count divided by the wall-clock completion window,
      never by the sum of individual task durations.
    - worker_utilization: each observed worker's busy execution seconds divided
      by the shared execution observation window.
    """
    metrics = collect_all_metrics(tasks_dir)
    report = TelemetryReport(total_tasks=len(metrics))
    if not metrics:
        return report

    queue_times: list[float] = []
    exec_times: list[float] = []
    review_times: list[float] = []
    cycle_times: list[float] = []
    worker_busy_seconds: dict[str, float] = {}

    all_timestamps: list[datetime] = []
    completed_created: list[datetime] = []
    completed_done: list[datetime] = []
    execution_starts: list[datetime] = []
    execution_ends: list[datetime] = []

    for metric in metrics:
        if metric.is_terminal:
            report.terminal_tasks += 1
        if metric.is_evaluated:
            report.evaluated_tasks += 1
        if metric.is_executed:
            report.executed_tasks += 1
        if metric.is_completed:
            report.completed_tasks += 1
        if metric.is_first_pass:
            report.first_pass_count += 1
        if metric.is_fix:
            report.fix_count += 1
        if metric.is_retry:
            report.retry_count += 1
        if metric.is_timeout:
            report.timeout_count += 1
        if metric.is_cancelled:
            report.cancel_count += 1
        if metric.status == REVIEW_REQUIRED:
            report.review_required_count += 1

        queue_time = metric.queue_time_seconds
        execution_time = metric.execution_time_seconds
        review_time = metric.review_time_seconds
        cycle_time = metric.total_cycle_time_seconds
        if queue_time is not None:
            queue_times.append(queue_time)
        if execution_time is not None:
            exec_times.append(execution_time)
            if metric.worker_id:
                worker_busy_seconds[metric.worker_id] = (
                    worker_busy_seconds.get(metric.worker_id, 0.0) + execution_time
                )
        if review_time is not None:
            review_times.append(review_time)
        if cycle_time is not None:
            cycle_times.append(cycle_time)

        report.total_tokens += _token_total(metric.tokens)

        if metric.worker_id:
            report.worker_task_counts[metric.worker_id] = (
                report.worker_task_counts.get(metric.worker_id, 0) + 1
            )
        report.role_task_counts[metric.role] = report.role_task_counts.get(metric.role, 0) + 1

        created = metric._parse_ts(metric.created_at)
        done = metric._parse_ts(metric.done_at)
        exec_start = metric._parse_ts(metric.running_at) or metric._parse_ts(metric.started_at)
        exec_end = metric._parse_ts(metric.finished_at) or done

        for ts in (created, done, exec_start, exec_end):
            if ts is not None:
                all_timestamps.append(ts)

        if metric.is_completed and created and done:
            completed_created.append(created)
            completed_done.append(done)

        if metric.is_executed and exec_start:
            execution_starts.append(exec_start)
            if exec_end:
                execution_ends.append(exec_end)

    report.avg_queue_time_seconds = _avg(queue_times)
    report.avg_execution_time_seconds = _avg(exec_times)
    report.avg_review_time_seconds = _avg(review_times)
    report.avg_total_cycle_time_seconds = _avg(cycle_times)

    if all_timestamps:
        report.window_start = min(all_timestamps).isoformat()
        report.window_end = max(all_timestamps).isoformat()

    if completed_created and completed_done:
        completion_window = (max(completed_done) - min(completed_created)).total_seconds()
        if completion_window > 0:
            report.tasks_per_hour = report.completed_tasks / (completion_window / 3600.0)

    if execution_starts and execution_ends:
        exec_start = min(execution_starts)
        exec_end = max(execution_ends)
        report.execution_window_start = exec_start.isoformat()
        report.execution_window_end = exec_end.isoformat()
        observation_seconds = (exec_end - exec_start).total_seconds()
        if observation_seconds > 0:
            report.worker_utilization = {
                worker_id: busy / observation_seconds
                for worker_id, busy in sorted(worker_busy_seconds.items())
            }
            report.avg_worker_utilization = _avg(list(report.worker_utilization.values()))

    evaluated_base = report.evaluated_tasks
    executed_base = report.executed_tasks
    report.first_pass_rate = report.first_pass_count / evaluated_base if evaluated_base else 0.0
    report.fix_rate = report.fix_count / evaluated_base if evaluated_base else 0.0
    report.retry_rate = report.retry_count / executed_base if executed_base else 0.0
    report.timeout_rate = report.timeout_count / executed_base if executed_base else 0.0

    return report


def report_to_dict(report: TelemetryReport) -> dict[str, Any]:
    """Return a JSON-serializable report for automation and AI consumers."""
    return asdict(report)


def format_report_text(report: TelemetryReport) -> str:
    """Format a telemetry report as human-readable text."""

    def _fmt_seconds(value: float | None) -> str:
        if value is None:
            return "N/A"
        if value < 60:
            return f"{value:.1f}s"
        return f"{value / 60:.1f}m"

    lines = [
        "=== Telemetry Report ===",
        f"Total tasks:         {report.total_tasks}",
        f"Terminal tasks:      {report.terminal_tasks}",
        f"Evaluated tasks:     {report.evaluated_tasks}",
        f"Executed tasks:      {report.executed_tasks}",
        f"Completed tasks:     {report.completed_tasks}",
        f"Review required:     {report.review_required_count}",
        "",
        "--- Quality ---",
        f"First pass count:    {report.first_pass_count}",
        f"First pass rate:     {report.first_pass_rate:.1%} (evaluated denominator)",
        f"Fix count:           {report.fix_count}",
        f"Fix rate:            {report.fix_rate:.1%} (evaluated denominator)",
        f"Retry count:         {report.retry_count}",
        f"Retry rate:          {report.retry_rate:.1%} (executed denominator)",
        f"Timeout count:       {report.timeout_count}",
        f"Timeout rate:        {report.timeout_rate:.1%} (executed denominator)",
        f"Cancel count:        {report.cancel_count}",
        "",
        "--- Timing ---",
        f"Avg queue time:      {_fmt_seconds(report.avg_queue_time_seconds)}",
        f"Avg execution time:  {_fmt_seconds(report.avg_execution_time_seconds)}",
        f"Avg review time:     {_fmt_seconds(report.avg_review_time_seconds)}",
        f"Avg total cycle:     {_fmt_seconds(report.avg_total_cycle_time_seconds)}",
        f"Tasks per hour:      {report.tasks_per_hour:.2f}" if report.tasks_per_hour is not None else "Tasks per hour:      N/A",
        "",
        "--- Resources ---",
        f"Total tokens:        {report.total_tokens}",
        f"Avg worker util:     {report.avg_worker_utilization:.1%}" if report.avg_worker_utilization is not None else "Avg worker util:     N/A",
    ]

    if report.worker_task_counts:
        lines.extend(["", "--- Worker Task Counts ---"])
        for worker_id, count in sorted(report.worker_task_counts.items()):
            utilization = report.worker_utilization.get(worker_id)
            suffix = f", util={utilization:.1%}" if utilization is not None else ""
            lines.append(f"  {worker_id}: {count}{suffix}")

    if report.role_task_counts:
        lines.extend(["", "--- Role Task Counts ---"])
        for role, count in sorted(report.role_task_counts.items()):
            lines.append(f"  {role}: {count}")

    if report.window_start and report.window_end:
        lines.extend([
            "",
            "--- Window ---",
            f"  Start: {report.window_start}",
            f"  End:   {report.window_end}",
        ])

    return "\n".join(lines)


def generate_report_text(tasks_dir: str | Path) -> str:
    """Convenience: generate and format a report in one call."""
    return format_report_text(generate_report(tasks_dir))
