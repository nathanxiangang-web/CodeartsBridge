# AI生成
"""E2E tests for P2-01: auto-dispatch engine."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.auto_dispatch import auto_dispatch, AutoDispatchResult
from bridge.dispatch import execute_dispatch
from bridge.state import READY, QUEUED, DONE, RUNNING


# --- Helpers ---

def _create_task(
    bridge_root: Path,
    task_id: str,
    state: str = "READY",
    depends_on: list[str] | None = None,
    priority: int = 50,
    role: str = "implement",
    project_id: str = "test-local",
    worker_id: str | None = None,
) -> Path:
    """Create a task directory with state.json and META.json."""
    task_dir = bridge_root / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    state_data = {
        "schemaVersion": 1,
        "taskId": task_id,
        "state": state,
        "status": state,
        "attempt": 0,
    }
    (task_dir / "state.json").write_text(
        json.dumps(state_data, indent=2), encoding="utf-8"
    )

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
    (task_dir / "META.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return task_dir


def _set_task_state(bridge_root: Path, task_id: str, state: str) -> None:
    """Manually set a task state (bypassing the state machine)."""
    task_dir = bridge_root / "tasks" / task_id
    state_data = json.loads(
        (task_dir / "state.json").read_text(encoding="utf-8")
    )
    state_data["state"] = state
    state_data["status"] = state
    (task_dir / "state.json").write_text(
        json.dumps(state_data, indent=2), encoding="utf-8"
    )


def _get_task_state(bridge_root: Path, task_id: str) -> str:
    """Read a task state."""
    task_dir = bridge_root / "tasks" / task_id
    data = json.loads(
        (task_dir / "state.json").read_text(encoding="utf-8")
    )
    return data.get("status") or data.get("state", "")


class _MockPopen:
    """Mock subprocess.Popen to avoid spawning real worker processes."""

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
    """Replace subprocess.Popen with a mock."""
    calls = []
    original = _MockPopen

    def _fake_popen(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    return calls


# --- Tests ---

class TestAutoDispatchReadyTasks:
    """Test 1: Auto-dispatch picks READY tasks with DONE dependencies and dispatches them."""

    def test_dispatches_ready_task_with_done_deps(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "t1", state="READY", depends_on=["t0"])
        _create_task(bridge_root, "t0", state="DONE")

        result = auto_dispatch(bridge_root, max_workers=4)

        assert result.planned == 1
        assert result.dispatched == 1
        assert _get_task_state(bridge_root, "t1") == QUEUED
        state_data = json.loads((bridge_root / "tasks" / "t1" / "state.json").read_text())
        assert state_data["assignedWorkerId"] == result.assignments[0]["workerId"]
        assert len(mock_popen) == 1

    def test_dispatches_ready_task_no_deps(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "t1", state="READY")

        result = auto_dispatch(bridge_root, max_workers=4)

        assert result.planned == 1
        assert result.dispatched == 1
        assert _get_task_state(bridge_root, "t1") == QUEUED


class TestAutoDispatchPendingDeps:
    """Test 2: Tasks with pending dependencies are skipped (not dispatched)."""

    def test_skips_task_with_running_dep(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "t1", state="READY", depends_on=["t0"])
        _create_task(bridge_root, "t0", state="RUNNING")

        result = auto_dispatch(bridge_root, max_workers=4)

        assert result.planned == 0
        assert result.dispatched == 0
        assert result.skipped == 1
        assert _get_task_state(bridge_root, "t1") == READY
        assert len(mock_popen) == 0

    def test_skips_task_with_ready_dep(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "t1", state="READY", depends_on=["t0"])
        _create_task(bridge_root, "t0", state="READY")

        result = auto_dispatch(bridge_root, max_workers=4)

        # t0 (no deps) gets dispatched; t1 (dep on t0 not DONE) is skipped
        assert result.skipped == 1
        assert _get_task_state(bridge_root, "t1") == READY
        assert _get_task_state(bridge_root, "t0") == QUEUED


class TestAutoDispatchPriority:
    """Test 3: Priority ordering is respected (higher priority dispatched first)."""

    def test_higher_priority_dispatched_first(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "low", state="READY", priority=10)
        _create_task(bridge_root, "high", state="READY", priority=90)

        result = auto_dispatch(bridge_root, max_workers=1)

        assert result.planned == 1
        assert result.dispatched == 1
        assert _get_task_state(bridge_root, "high") == QUEUED
        assert _get_task_state(bridge_root, "low") == READY

    def test_priority_ordering_with_max_workers_2(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "low", state="READY", priority=10)
        _create_task(bridge_root, "high", state="READY", priority=90)
        _create_task(bridge_root, "mid", state="READY", priority=50)

        result = auto_dispatch(bridge_root, max_workers=2)

        assert result.dispatched == 2
        assert _get_task_state(bridge_root, "high") == QUEUED
        assert _get_task_state(bridge_root, "mid") == QUEUED
        assert _get_task_state(bridge_root, "low") == READY


class TestAutoDispatchIdempotency:
    """Test 4: Idempotency: running auto-dispatch twice does not double-dispatch."""

    def test_double_dispatch_same_task(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "t1", state="READY")

        result1 = auto_dispatch(bridge_root, max_workers=4)
        assert result1.dispatched == 1
        assert _get_task_state(bridge_root, "t1") == QUEUED

        result2 = auto_dispatch(bridge_root, max_workers=4)
        assert result2.planned == 0
        assert result2.dispatched == 0
        assert _get_task_state(bridge_root, "t1") == QUEUED

    def test_idempotency_with_multiple_tasks(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "t1", state="READY")
        _create_task(bridge_root, "t2", state="READY")

        result1 = auto_dispatch(bridge_root, max_workers=4)
        assert result1.dispatched == 2

        result2 = auto_dispatch(bridge_root, max_workers=4)
        assert result2.planned == 0
        assert result2.dispatched == 0


class TestAutoDispatchDryRun:
    """Test 5: --dry-run shows plan without dispatching."""

    def test_dry_run_does_not_dispatch(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "t1", state="READY")

        result = auto_dispatch(bridge_root, max_workers=4, dry_run=True)

        assert result.planned == 1
        assert result.dispatched == 0
        assert result.dry_run is True
        assert _get_task_state(bridge_root, "t1") == READY
        assert len(mock_popen) == 0

    def test_dry_run_shows_assignment(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "t1", state="READY")

        result = auto_dispatch(bridge_root, max_workers=4, dry_run=True)

        assert len(result.assignments) == 1
        assert result.assignments[0]["taskId"] == "t1"

    def test_dry_run_with_blocked_dep(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "t1", state="READY", depends_on=["t0"])
        _create_task(bridge_root, "t0", state="RUNNING")

        result = auto_dispatch(bridge_root, max_workers=4, dry_run=True)

        assert result.planned == 0
        assert result.skipped == 1
        assert _get_task_state(bridge_root, "t1") == READY


class TestAutoDispatchDependencyChain:
    """Test 6: Dependency chain test: create tasks A->B->C, auto-dispatch resolves correctly."""

    def test_chain_a_b_c(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "A", state="READY", priority=50)
        _create_task(bridge_root, "B", state="READY", depends_on=["A"], priority=50)
        _create_task(bridge_root, "C", state="READY", depends_on=["B"], priority=50)

        # Cycle 1: only A can be dispatched (B and C have pending deps)
        result1 = auto_dispatch(bridge_root, max_workers=4)
        assert result1.dispatched == 1
        assert _get_task_state(bridge_root, "A") == QUEUED
        assert _get_task_state(bridge_root, "B") == READY
        assert _get_task_state(bridge_root, "C") == READY

        # Mark A as DONE
        _set_task_state(bridge_root, "A", "DONE")

        # Cycle 2: B can be dispatched (A is DONE), C still blocked
        result2 = auto_dispatch(bridge_root, max_workers=4)
        assert result2.dispatched == 1
        assert _get_task_state(bridge_root, "B") == QUEUED
        assert _get_task_state(bridge_root, "C") == READY

        # Mark B as DONE
        _set_task_state(bridge_root, "B", "DONE")

        # Cycle 3: C can be dispatched
        result3 = auto_dispatch(bridge_root, max_workers=4)
        assert result3.dispatched == 1
        assert _get_task_state(bridge_root, "C") == QUEUED

    def test_chain_parallel_dispatch(self, setup_bridge, mock_popen):
        """A has no deps, B has no deps, C depends on both A and B."""
        bridge_root = setup_bridge
        _create_task(bridge_root, "A", state="READY", priority=50)
        _create_task(bridge_root, "B", state="READY", priority=50)
        _create_task(bridge_root, "C", state="READY", depends_on=["A", "B"], priority=50)

        # Cycle 1: A and B can be dispatched, C is blocked
        result1 = auto_dispatch(bridge_root, max_workers=4)
        assert result1.dispatched == 2
        assert _get_task_state(bridge_root, "A") == QUEUED
        assert _get_task_state(bridge_root, "B") == QUEUED
        assert _get_task_state(bridge_root, "C") == READY

        # Mark A and B as DONE
        _set_task_state(bridge_root, "A", "DONE")
        _set_task_state(bridge_root, "B", "DONE")

        # Cycle 2: C can now be dispatched
        result2 = auto_dispatch(bridge_root, max_workers=4)
        assert result2.dispatched == 1
        assert _get_task_state(bridge_root, "C") == QUEUED


class TestAutoDispatchNoRegression:
    """Test 7: No regression: existing bridge dispatch still works."""

    def test_execute_dispatch_still_works(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        tasks_root = bridge_root / "tasks"
        _create_task(bridge_root, "t1", state="READY")

        result = execute_dispatch(
            tasks_root, bridge_root,
            max_workers=4,
            dry_run=False,
        )

        assert len(result.plan.plan) == 1
        assert len(result.spawned) == 1
        assert _get_task_state(bridge_root, "t1") == QUEUED
        state_data = json.loads((bridge_root / "tasks" / "t1" / "state.json").read_text())
        assert state_data["assignedWorkerId"] == result.plan.plan[0].worker_id

    def test_execute_dispatch_dry_run_still_works(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        tasks_root = bridge_root / "tasks"
        _create_task(bridge_root, "t1", state="READY")

        result = execute_dispatch(
            tasks_root, bridge_root,
            max_workers=4,
            dry_run=True,
        )

        assert len(result.plan.plan) == 1
        assert _get_task_state(bridge_root, "t1") == READY

    def test_manual_and_auto_dispatch_coexist(self, setup_bridge, mock_popen):
        """Both auto_dispatch and execute_dispatch can be used without breaking each other."""
        bridge_root = setup_bridge
        tasks_root = bridge_root / "tasks"
        _create_task(bridge_root, "t1", state="READY")
        _create_task(bridge_root, "t2", state="READY")

        # Use auto_dispatch for t1
        result1 = auto_dispatch(bridge_root, max_workers=1)
        assert result1.dispatched == 1

        # Use execute_dispatch for t2
        result2 = execute_dispatch(tasks_root, bridge_root, max_workers=4)
        assert len(result2.spawned) == 1

        assert _get_task_state(bridge_root, "t1") == QUEUED
        assert _get_task_state(bridge_root, "t2") == QUEUED

class TestAssignmentLeaseLifecycle:
    """Runtime assignments must release worker capacity after execution."""

    def test_finish_assignment_marks_done_and_releases_lease(self, setup_bridge, mock_popen):
        from bridge.scheduler.planner import finish_assignment, load_assignments

        bridge_root = setup_bridge
        _create_task(bridge_root, "lease-t1", state="READY")

        result = auto_dispatch(bridge_root, max_workers=1)
        assert result.dispatched == 1

        assignments_dir = bridge_root / "runtime" / "assignments"
        leases_dir = bridge_root / "runtime" / "leases"
        active = [a for a in load_assignments(assignments_dir) if a.task_id == "lease-t1"]
        assert len(active) == 1
        assert active[0].finished_at is None
        assert active[0].lease_id
        assert (leases_dir / f"{active[0].lease_id}.json").is_file()

        assert finish_assignment(assignments_dir, leases_dir, "lease-t1") == 1

        finished = [a for a in load_assignments(assignments_dir) if a.task_id == "lease-t1"]
        assert finished[0].finished_at is not None
        assert not (leases_dir / f"{finished[0].lease_id}.json").exists()

    def test_next_dispatch_reconciles_terminal_assignment_capacity(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "first", state="READY", priority=100)
        _create_task(bridge_root, "second", state="READY", priority=10)

        first = auto_dispatch(bridge_root, max_workers=1)
        assert first.dispatched == 1
        assert _get_task_state(bridge_root, "first") == QUEUED
        assert _get_task_state(bridge_root, "second") == READY

        # Simulate a worker/service ending without running normal finally cleanup.
        _set_task_state(bridge_root, "first", "DONE")

        second = auto_dispatch(bridge_root, max_workers=1)
        assert second.dispatched == 1
        assert _get_task_state(bridge_root, "second") == QUEUED

        first_assignment = next(
            p for p in (bridge_root / "runtime" / "assignments").glob("*.json")
            if json.loads(p.read_text(encoding="utf-8")).get("taskId") == "first"
        )
        assert json.loads(first_assignment.read_text(encoding="utf-8")).get("finishedAt")

    def test_run_worker_finally_finishes_assignment(self, tmp_path, monkeypatch):
        import bridge.worker as worker_module

        task_dir = tmp_path / "tasks" / "wrapped"
        task_dir.mkdir(parents=True)
        calls = []

        monkeypatch.setattr(
            worker_module,
            "_run_worker_inner",
            lambda *args, **kwargs: {"status": "DONE"},
        )
        monkeypatch.setattr(
            "bridge.scheduler.planner.finish_assignment",
            lambda assignments, leases, task_id: calls.append(
                (assignments, leases, task_id)
            ) or 1,
        )

        result = worker_module.run_worker(
            task_dir,
            project=object(),
            worker=None,
            bridge_root=tmp_path,
        )

        assert result == {"status": "DONE"}
        assert calls == [(
            tmp_path / "runtime" / "assignments",
            tmp_path / "runtime" / "leases",
            "wrapped",
        )]

class TestExplicitWorkerRouting:
    """Explicit META.workerId is a hard routing constraint."""

    def test_auto_dispatch_honors_explicit_worker(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "pinned", worker_id="w3")

        result = auto_dispatch(bridge_root, max_workers=1)

        assert result.dispatched == 1
        assert result.assignments[0]["workerId"] == "w3"
        state_data = json.loads(
            (bridge_root / "tasks" / "pinned" / "state.json").read_text(encoding="utf-8")
        )
        assert state_data["assignedWorkerId"] == "w3"

    def test_missing_explicit_worker_never_falls_back(self, setup_bridge, mock_popen):
        bridge_root = setup_bridge
        _create_task(bridge_root, "missing-worker", worker_id="does-not-exist")

        result = auto_dispatch(bridge_root, max_workers=1)

        assert result.dispatched == 0
        assert result.planned == 0
        assert _get_task_state(bridge_root, "missing-worker") == READY
        detail = next(
            item for item in result.skipped_details
            if item["taskId"] == "missing-worker"
        )
        assert detail["reason"] == "explicit_worker_unavailable"
        assert detail["workerId"] == "does-not-exist"
        assert len(mock_popen) == 0

    def test_task_model_round_trips_explicit_worker(self):
        from bridge.core.models import Task

        task = Task.from_dict({
            "taskId": "roundtrip",
            "projectId": "p1",
            "workerId": "w3",
            "role": "implement",
        })

        assert task.worker_id == "w3"
        assert task.to_dict()["workerId"] == "w3"

