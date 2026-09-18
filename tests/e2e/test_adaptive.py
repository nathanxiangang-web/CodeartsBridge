"""P3-01: adaptive scheduling strategy tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.adaptive import (
    WorkerPerformance,
    collect_worker_stats,
    recommend_timeout,
    recommend_worker,
    adaptive_dispatch,
    DEFAULT_TIMEOUT_MINUTES,
    MIN_TASKS_FOR_RECOMMENDATION,
)
from bridge.atomic import atomic_write_json
from bridge.state import (
    set_state, get_state,
    READY, QUEUED, STARTING, RUNNING,
    REVIEW_REQUIRED, DONE, FAILED, FIX_REQUIRED, CANCELLED,
)


# --- Helpers ---

def _make_task(
    bridge_root: Path,
    task_id: str,
    worker_id: str,
    status: str = DONE,
    role: str = "implement",
    project_id: str = "test-local",
    attempt: int = 1,
    started_at: datetime | None = None,
    duration_seconds: float = 60.0,
    exit_code: int | None = None,
) -> Path:
    """Create a task dir with state.json and META.json simulating a completed run."""
    task_dir = bridge_root / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "schemaVersion": 2,
        "taskId": task_id,
        "projectId": project_id,
        "role": role,
        "workerId": worker_id,
        "priority": 50,
        "execution": {
            "targetMinutes": 10,
            "softTimeoutMinutes": 12,
            "hardTimeoutMinutes": 15,
        },
    }
    atomic_write_json(task_dir / "META.json", meta)

    now = started_at or datetime.now(timezone.utc)
    start_iso = now.isoformat()
    finish_iso = (now + timedelta(seconds=duration_seconds)).isoformat()

    state = {
        "schemaVersion": 1,
        "taskId": task_id,
        "status": status,
        "state": status,
        "attempt": attempt,
        "startedAt": start_iso,
        "finishedAt": finish_iso,
        "updatedAt": finish_iso,
    }
    if exit_code is not None:
        state["exitCode"] = exit_code
    atomic_write_json(task_dir / "state.json", state)
    return task_dir


def _make_candidate_task(
    bridge_root: Path,
    task_id: str,
    state: str = READY,
    role: str = "implement",
    project_id: str = "test-local",
    priority: int = 50,
    depends_on: list[str] | None = None,
    worker_id: str | None = None,
) -> Path:
    """Create a candidate-state task for dispatch."""
    task_dir = bridge_root / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    state_data = {
        "schemaVersion": 1,
        "taskId": task_id,
        "state": state,
        "status": state,
        "attempt": 0,
    }
    atomic_write_json(task_dir / "state.json", state_data)
    meta = {
        "schemaVersion": 2,
        "taskId": task_id,
        "projectId": project_id,
        "role": role,
        "dependsOn": depends_on or [],
        "priority": priority,
        "execution": {
            "targetMinutes": 10,
            "softTimeoutMinutes": 12,
            "hardTimeoutMinutes": 15,
        },
    }
    if worker_id is not None:
        meta["workerId"] = worker_id
    atomic_write_json(task_dir / "META.json", meta)
    return task_dir


class _MockPopen:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pid = 0
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def communicate(self):
        return (b"", b"")


@pytest.fixture
def mock_popen(monkeypatch):
    calls = []

    def _fake_popen(*args, **kwargs):
        calls.append(args)
        return _MockPopen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    return calls


# --- Tests ---

class TestWorkerPerformanceDataclass:
    """Test 1: WorkerPerformance dataclass."""

    def test_defaults(self):
        wp = WorkerPerformance(worker_id="w1")
        assert wp.worker_id == "w1"
        assert wp.task_count == 0
        assert wp.success_rate == 0.0
        assert wp.avg_duration == 0.0
        assert wp.timeout_rate == 0.0
        assert wp.last_updated == ""


class TestCollectWorkerStats:
    """Tests for collect_worker_stats."""

    def test_empty_tasks_dir(self, bridge_root):
        """Test 2: empty tasks dir returns empty dict."""
        stats = collect_worker_stats(bridge_root)
        assert stats == {}

    def test_single_worker_stats(self, bridge_root):
        """Test 3: one worker with several tasks computes correct stats."""
        base = datetime.now(timezone.utc)
        _make_task(bridge_root, "t1", "w1", status=DONE, duration_seconds=120, started_at=base)
        _make_task(bridge_root, "t2", "w1", status=DONE, duration_seconds=180, started_at=base)
        _make_task(bridge_root, "t3", "w1", status=FAILED, duration_seconds=60, started_at=base)

        stats = collect_worker_stats(bridge_root)
        assert "w1" in stats
        perf = stats["w1"]
        assert perf.worker_id == "w1"
        assert perf.task_count == 3
        assert perf.success_rate == pytest.approx(2 / 3)
        assert perf.avg_duration == pytest.approx((120 + 180 + 60) / 3)
        assert perf.timeout_rate == 0.0

    def test_multiple_workers(self, bridge_root):
        """Test 4: multiple workers are tracked independently."""
        base = datetime.now(timezone.utc)
        _make_task(bridge_root, "t1", "w1", status=DONE, duration_seconds=100, started_at=base)
        _make_task(bridge_root, "t2", "w1", status=DONE, duration_seconds=200, started_at=base)
        _make_task(bridge_root, "t3", "w2", status=DONE, duration_seconds=50, started_at=base)
        _make_task(bridge_root, "t4", "w2", status=FAILED, duration_seconds=70, started_at=base)

        stats = collect_worker_stats(bridge_root)
        assert set(stats.keys()) == {"w1", "w2"}
        assert stats["w1"].task_count == 2
        assert stats["w2"].task_count == 2
        assert stats["w1"].avg_duration == pytest.approx(150.0)
        assert stats["w2"].avg_duration == pytest.approx(60.0)

    def test_timeout_rate(self, bridge_root):
        """Test 5: timeout_rate counts exit_code 137/124 in terminal states."""
        base = datetime.now(timezone.utc)
        _make_task(bridge_root, "t1", "w1", status=DONE, duration_seconds=100, started_at=base)
        _make_task(bridge_root, "t2", "w1", status=FAILED, duration_seconds=900, started_at=base, exit_code=137)
        _make_task(bridge_root, "t3", "w1", status=DONE, duration_seconds=110, started_at=base)

        stats = collect_worker_stats(bridge_root)
        perf = stats["w1"]
        assert perf.task_count == 3
        assert perf.timeout_rate == pytest.approx(1 / 3)

    def test_skips_tasks_without_execution_time(self, bridge_root):
        """Test 6: tasks missing started_at/finished_at do not contribute."""
        task_dir = bridge_root / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        atomic_write_json(task_dir / "META.json", {
            "taskId": "t1", "workerId": "w1", "role": "implement", "projectId": "p1",
        })
        atomic_write_json(task_dir / "state.json", {
            "taskId": "t1", "status": DONE, "state": DONE, "attempt": 1,
        })
        stats = collect_worker_stats(bridge_root)
        assert stats == {}


class TestRecommendTimeout:
    """Tests for recommend_timeout."""

    def test_fallback_no_history(self, bridge_root):
        """Test 7: no historical data returns default 15 min."""
        _make_candidate_task(bridge_root, "target", role="implement", project_id="p1")
        result = recommend_timeout("target", bridge_root)
        assert result == DEFAULT_TIMEOUT_MINUTES

    def test_fallback_insufficient_history(self, bridge_root):
        """Test 8: fewer than MIN_TASKS_FOR_RECOMMENDATION returns default."""
        base = datetime.now(timezone.utc)
        _make_task(bridge_root, "h1", "w1", role="implement", project_id="p1",
                   duration_seconds=120, started_at=base)
        _make_candidate_task(bridge_root, "target", role="implement", project_id="p1")
        result = recommend_timeout("target", bridge_root)
        assert result == DEFAULT_TIMEOUT_MINUTES

    def test_returns_avg_plus_2sigma(self, bridge_root):
        """Test 9: with enough data, returns (avg + 2*sigma) in minutes, clamped."""
        base = datetime.now(timezone.utc)
        _make_task(bridge_root, "h1", "w1", role="implement", project_id="p1",
                   duration_seconds=60, started_at=base)
        _make_task(bridge_root, "h2", "w1", role="implement", project_id="p1",
                   duration_seconds=60, started_at=base)
        _make_task(bridge_root, "h3", "w1", role="implement", project_id="p1",
                   duration_seconds=60, started_at=base)
        _make_candidate_task(bridge_root, "target", role="implement", project_id="p1")

        result = recommend_timeout("target", bridge_root)
        assert isinstance(result, float)
        assert 1.0 <= result <= 60.0
        assert result == pytest.approx(1.0)

    def test_role_project_filtering(self, bridge_root):
        """Test 10: only same role+project tasks are used for timeout estimate."""
        base = datetime.now(timezone.utc)
        _make_task(bridge_root, "h1", "w1", role="review", project_id="p1",
                   duration_seconds=600, started_at=base)
        _make_task(bridge_root, "h2", "w1", role="review", project_id="p1",
                   duration_seconds=600, started_at=base)
        _make_task(bridge_root, "h3", "w1", role="review", project_id="p1",
                   duration_seconds=600, started_at=base)
        _make_candidate_task(bridge_root, "target", role="implement", project_id="p1")

        result = recommend_timeout("target", bridge_root)
        assert result == DEFAULT_TIMEOUT_MINUTES

    def test_missing_task_meta(self, bridge_root):
        """Test 11: missing META.json for target returns default."""
        result = recommend_timeout("nonexistent", bridge_root)
        assert result == DEFAULT_TIMEOUT_MINUTES


class TestRecommendWorker:
    """Tests for recommend_worker."""

    def test_insufficient_data_returns_none(self, bridge_root):
        """Test 12: workers with < MIN_TASKS_FOR_RECOMMENDATION tasks return None."""
        base = datetime.now(timezone.utc)
        _make_task(bridge_root, "h1", "w1", status=DONE, duration_seconds=60, started_at=base)
        _make_candidate_task(bridge_root, "target")

        result = recommend_worker("target", bridge_root, ["w1"])
        assert result is None

    def test_returns_best_scoring_worker(self, bridge_root):
        """Test 13: returns the highest-scoring worker."""
        base = datetime.now(timezone.utc)
        for i in range(4):
            _make_task(bridge_root, f"good-{i}", "good", status=DONE,
                       duration_seconds=60, started_at=base)
        for i in range(4):
            _make_task(bridge_root, f"bad-{i}", "bad", status=FAILED,
                       duration_seconds=300, started_at=base)
        _make_candidate_task(bridge_root, "target")

        result = recommend_worker("target", bridge_root, ["good", "bad"])
        assert result == "good"

    def test_no_candidates_returns_none(self, bridge_root):
        """Test 14: empty candidate list returns None."""
        base = datetime.now(timezone.utc)
        for i in range(3):
            _make_task(bridge_root, f"h{i}", "w1", status=DONE,
                       duration_seconds=60, started_at=base)
        result = recommend_worker("target", bridge_root, [])
        assert result is None

    def test_accepts_worker_objects(self, bridge_root):
        """Test 15: candidates may be objects with .id attribute."""

        class _W:
            def __init__(self, wid):
                self.id = wid

        base = datetime.now(timezone.utc)
        for i in range(3):
            _make_task(bridge_root, f"h{i}", "w1", status=DONE,
                       duration_seconds=60, started_at=base)
        result = recommend_worker("target", bridge_root, [_W("w1")])
        assert result == "w1"


class TestAdaptiveDispatch:
    """Tests for adaptive_dispatch."""

    def test_dry_run_does_not_dispatch(self, setup_bridge, mock_popen):
        """Test 16: dry_run passes through to auto_dispatch without spawning."""
        bridge_root = setup_bridge
        _make_candidate_task(bridge_root, "t1", state=READY)

        result = adaptive_dispatch(bridge_root, max_workers=4, dry_run=True)

        assert result.dry_run is True
        assert result.dispatched == 0
        assert len(mock_popen) == 0

    def test_dispatches_ready_task(self, setup_bridge, mock_popen):
        """Test 17: adaptive_dispatch dispatches a ready task."""
        bridge_root = setup_bridge
        _make_candidate_task(bridge_root, "t1", state=READY)

        result = adaptive_dispatch(bridge_root, max_workers=4, dry_run=False)

        assert result.dispatched == 1
        assert len(mock_popen) == 1

    def test_adapts_timeout_in_meta(self, setup_bridge, mock_popen):
        """Test 18: adaptive_dispatch updates hardTimeoutMinutes when history justifies it."""
        bridge_root = setup_bridge
        base = datetime.now(timezone.utc)
        for i in range(3):
            _make_task(bridge_root, f"hist-{i}", "w1", role="implement",
                       project_id="test-local", status=DONE,
                       duration_seconds=600, started_at=base)
        _make_candidate_task(bridge_root, "target", role="implement", project_id="test-local")

        adaptive_dispatch(bridge_root, max_workers=4, dry_run=True)

        meta = json.loads(
            (bridge_root / "tasks" / "target" / "META.json").read_text()
        )
        hard = meta["execution"]["hardTimeoutMinutes"]
        assert hard != 15
        assert 1 <= hard <= 60

    def test_explicit_worker_is_not_replaced_by_adaptive_preference(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        base = datetime.now(timezone.utc)

        # Give w1 enough strong history that adaptive routing would normally prefer it.
        for i in range(4):
            _make_task(
                bridge_root, f"hist-good-{i}", "w1",
                role="implement", project_id="test-local",
                status=DONE, duration_seconds=30, started_at=base,
            )
        _make_candidate_task(
            bridge_root,
            "pinned-target",
            role="implement",
            project_id="test-local",
            worker_id="w3",
        )

        result = adaptive_dispatch(bridge_root, max_workers=1, dry_run=True)

        meta = json.loads(
            (bridge_root / "tasks" / "pinned-target" / "META.json").read_text()
        )
        assert meta["workerId"] == "w3"
        assert meta["execution"].get("preferredWorker") is None
        assert result.assignments[0]["workerId"] == "w3"

    def test_no_adaptation_when_history_empty(self, setup_bridge, mock_popen):
        """Test 19: with no history, META.json is left unchanged."""
        bridge_root = setup_bridge
        _make_candidate_task(bridge_root, "t1", state=READY)

        adaptive_dispatch(bridge_root, max_workers=4, dry_run=True)

        meta = json.loads(
            (bridge_root / "tasks" / "t1" / "META.json").read_text()
        )
        assert meta["execution"]["hardTimeoutMinutes"] == 15
