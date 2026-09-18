"""P1-06: telemetry and statistics tests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.telemetry import (
    TaskMetrics,
    TelemetryReport,
    collect_all_metrics,
    generate_report,
    format_report_text,
    generate_report_text,
    report_to_dict,
)
from bridge.state import (
    set_state, get_state, READY, QUEUED, STARTING, RUNNING,
    REVIEW_REQUIRED, DONE, FAILED, FIX_REQUIRED, CANCELLED,
)
from bridge.atomic import atomic_write_json


def _make_task(tmp_path, task_id, status_sequence, attempt=1, role="implement", worker_id="w01"):
    """Create a task dir with a sequence of state transitions."""
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    meta = {
        "taskId": task_id,
        "role": role,
        "workerId": worker_id,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(task_dir / "META.json", meta)
    for status in status_sequence:
        set_state(task_dir, status, attempt=attempt)
    return task_dir


class TestTaskMetrics:
    """Test single task metric extraction."""

    def test_from_task_dir_basic(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED])
        m = TaskMetrics.from_task_dir(d)
        assert m.task_id == "t1"
        assert m.status == REVIEW_REQUIRED
        assert m.role == "implement"
        assert m.worker_id == "w01"
        assert m.queued_at is not None
        assert m.started_at is not None
        assert m.finished_at is not None

    def test_queue_time_seconds(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING])
        m = TaskMetrics.from_task_dir(d)
        assert m.queue_time_seconds is not None
        assert m.queue_time_seconds >= 0

    def test_execution_time_seconds(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED])
        m = TaskMetrics.from_task_dir(d)
        assert m.execution_time_seconds is not None
        assert m.execution_time_seconds >= 0

    def test_total_cycle_time_seconds(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE])
        m = TaskMetrics.from_task_dir(d)
        assert m.total_cycle_time_seconds is not None
        assert m.total_cycle_time_seconds >= 0

    def test_is_first_pass(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED], attempt=1)
        m = TaskMetrics.from_task_dir(d)
        assert m.is_first_pass is True

    def test_is_not_first_pass_on_attempt_2(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED], attempt=2)
        m = TaskMetrics.from_task_dir(d)
        assert m.is_first_pass is False

    def test_is_fix(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, FIX_REQUIRED], attempt=1)
        m = TaskMetrics.from_task_dir(d)
        assert m.is_fix is True

    def test_is_retry(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING], attempt=2)
        m = TaskMetrics.from_task_dir(d)
        assert m.is_retry is True

    def test_is_terminal(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE])
        m = TaskMetrics.from_task_dir(d)
        assert m.is_terminal is True

    def test_is_cancelled(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, CANCELLED])
        m = TaskMetrics.from_task_dir(d)
        assert m.is_cancelled is True

    def test_missing_state_returns_unknown(self, tmp_path):
        d = tmp_path / "tasks" / "empty"
        d.mkdir(parents=True)
        atomic_write_json(d / "META.json", {"taskId": "empty"})
        m = TaskMetrics.from_task_dir(d)
        assert m.status == "UNKNOWN"

    def test_parse_ts_invalid(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY])
        m = TaskMetrics.from_task_dir(d)
        assert m._parse_ts("not-a-timestamp") is None
        assert m._parse_ts(None) is None


class TestGenerateReport:
    """Test report aggregation."""

    def test_empty_tasks_dir(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        report = generate_report(tasks_dir)
        assert report.total_tasks == 0

    def test_nonexistent_tasks_dir(self, tmp_path):
        report = generate_report(tmp_path / "nonexistent")
        assert report.total_tasks == 0

    def test_single_task_report(self, tmp_path):
        _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE])
        report = generate_report(tmp_path / "tasks")
        assert report.total_tasks == 1
        assert report.terminal_tasks == 1
        assert report.first_pass_count == 1

    def test_multiple_tasks_with_retries(self, tmp_path):
        _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE], attempt=1)
        _make_task(tmp_path, "t2", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, FIX_REQUIRED], attempt=1)
        _make_task(tmp_path, "t3", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE], attempt=2)
        report = generate_report(tmp_path / "tasks")
        assert report.total_tasks == 3
        assert report.first_pass_count == 1
        assert report.fix_count >= 2
        assert report.retry_count == 1

    def test_worker_task_counts(self, tmp_path):
        _make_task(tmp_path, "t1", [READY, QUEUED], worker_id="w01")
        _make_task(tmp_path, "t2", [READY, QUEUED], worker_id="w02")
        _make_task(tmp_path, "t3", [READY, QUEUED], worker_id="w01")
        report = generate_report(tmp_path / "tasks")
        assert report.worker_task_counts.get("w01") == 2
        assert report.worker_task_counts.get("w02") == 1

    def test_role_task_counts(self, tmp_path):
        _make_task(tmp_path, "t1", [READY], role="implement")
        _make_task(tmp_path, "t2", [READY], role="review")
        _make_task(tmp_path, "t3", [READY], role="test")
        report = generate_report(tmp_path / "tasks")
        assert report.role_task_counts.get("implement") == 1
        assert report.role_task_counts.get("review") == 1
        assert report.role_task_counts.get("test") == 1

    def test_rates_calculation(self, tmp_path):
        _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE], attempt=1)
        _make_task(tmp_path, "t2", [READY, QUEUED, STARTING, RUNNING, FAILED], attempt=1)
        report = generate_report(tmp_path / "tasks")
        assert 0 <= report.first_pass_rate <= 1
        assert 0 <= report.fix_rate <= 1
        assert 0 <= report.retry_rate <= 1
        assert 0 <= report.timeout_rate <= 1

    def test_quality_rates_use_evaluated_denominator(self, tmp_path):
        _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE], attempt=1)
        _make_task(tmp_path, "t2", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE], attempt=2)
        _make_task(tmp_path, "t3", [READY], attempt=1)

        report = generate_report(tmp_path / "tasks")
        assert report.total_tasks == 3
        assert report.evaluated_tasks == 2
        assert report.executed_tasks == 2
        assert report.first_pass_count == 1
        assert report.first_pass_rate == pytest.approx(0.5)
        assert report.fix_count == 1
        assert report.fix_rate == pytest.approx(0.5)
        assert report.retry_rate == pytest.approx(0.5)

    def test_wall_clock_throughput_and_worker_utilization(self, tmp_path):
        t1 = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE], worker_id="w01")
        t2 = _make_task(tmp_path, "t2", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE], worker_id="w02")

        base = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)
        for task_dir, worker_minutes in ((t1, 30), (t2, 60)):
            meta = json.loads((task_dir / "META.json").read_text(encoding="utf-8"))
            meta["createdAt"] = base.isoformat()
            atomic_write_json(task_dir / "META.json", meta)
            state = get_state(task_dir)
            state["startedAt"] = base.isoformat()
            state["runningAt"] = base.isoformat()
            state["finishedAt"] = (base + timedelta(minutes=worker_minutes)).isoformat()
            state["doneAt"] = (base + timedelta(hours=1)).isoformat()
            atomic_write_json(task_dir / "state.json", state)

        report = generate_report(tmp_path / "tasks")
        assert report.completed_tasks == 2
        assert report.tasks_per_hour == pytest.approx(2.0)
        assert report.worker_utilization["w01"] == pytest.approx(0.5)
        assert report.worker_utilization["w02"] == pytest.approx(1.0)
        assert report.avg_worker_utilization == pytest.approx(0.75)

    def test_structured_tokens_and_json_report(self, tmp_path):
        task_dir = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED])
        state = get_state(task_dir)
        state["tokens"] = {"input_tokens": 120, "output_tokens": 80}
        atomic_write_json(task_dir / "state.json", state)
        data = report_to_dict(generate_report(tmp_path / "tasks"))
        assert data["total_tokens"] == 200
        assert data["evaluated_tasks"] == 1
        assert "worker_utilization" in data

    def test_tokens_aggregation(self, tmp_path):
        d = _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED])
        state = get_state(d)
        state["tokens"] = 500
        atomic_write_json(d / "state.json", state)
        d2 = _make_task(tmp_path, "t2", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED])
        state2 = get_state(d2)
        state2["tokens"] = 300
        atomic_write_json(d2 / "state.json", state2)
        report = generate_report(tmp_path / "tasks")
        assert report.total_tokens == 800


class TestFormatReport:
    """Test report formatting."""

    def test_empty_report_format(self):
        report = TelemetryReport()
        text = format_report_text(report)
        assert "Telemetry Report" in text
        assert "Total tasks:         0" in text

    def test_report_with_data(self, tmp_path):
        _make_task(tmp_path, "t1", [READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE])
        report = generate_report(tmp_path / "tasks")
        text = format_report_text(report)
        assert "Total tasks:         1" in text
        assert "First pass" in text
        assert "Timing" in text

    def test_generate_report_text_convenience(self, tmp_path):
        _make_task(tmp_path, "t1", [READY])
        text = generate_report_text(tmp_path / "tasks")
        assert "Telemetry Report" in text


class TestStateTimestamps:
    """Test that state.py auto-records timestamps."""

    def test_queued_at_recorded(self, tmp_path):
        d = tmp_path / "task1"
        d.mkdir()
        set_state(d, QUEUED)
        state = get_state(d)
        assert "queuedAt" in state
        assert state["queuedAt"] is not None

    def test_started_at_recorded(self, tmp_path):
        d = tmp_path / "task1"
        d.mkdir()
        set_state(d, STARTING)
        state = get_state(d)
        assert "startedAt" in state

    def test_finished_at_recorded(self, tmp_path):
        d = tmp_path / "task1"
        d.mkdir()
        set_state(d, REVIEW_REQUIRED)
        state = get_state(d)
        assert "finishedAt" in state

    def test_done_at_recorded(self, tmp_path):
        d = tmp_path / "task1"
        d.mkdir()
        set_state(d, DONE)
        state = get_state(d)
        assert "doneAt" in state

    def test_timestamp_not_overwritten(self, tmp_path):
        d = tmp_path / "task1"
        d.mkdir()
        set_state(d, QUEUED)
        first = get_state(d)["queuedAt"]
        set_state(d, RUNNING)
        set_state(d, QUEUED)
        second = get_state(d)["queuedAt"]
        assert first == second

    def test_cancelled_at_recorded(self, tmp_path):
        d = tmp_path / "task1"
        d.mkdir()
        set_state(d, CANCELLED)
        state = get_state(d)
        assert "cancelledAt" in state