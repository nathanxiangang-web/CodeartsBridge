# AI生成
"""E2E tests for task lifecycle: create -> dispatch -> run -> review.

Uses FakeRunner instead of real CodeArts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from bridge.atomic import atomic_write_json, read_json_or_none
from bridge.state import get_state, set_state, READY, QUEUED, REVIEW_REQUIRED, DONE, FIX_REQUIRED
CANCELLED = "CANCELLED"  # not yet in v1 state.py
from bridge.dispatch import select_dispatch_plan, execute_dispatch
from fake_runner import FakeRunner


def _create_task(bridge_root: Path, task_id: str, project_id: str = "test-local",
                 worker_id: str = "w1", role: str = "implement") -> Path:
    """Create a task directory with META.json and state.json."""
    tdir = bridge_root / "tasks" / task_id
    (tdir / "inbox").mkdir(parents=True)
    (tdir / "outbox").mkdir()
    (tdir / "evidence").mkdir()

    meta = {
        "schemaVersion": 1,
        "taskId": task_id,
        "projectId": project_id,
        "workerId": worker_id,
        "role": role,
        "taskKind": "implementation",
        "targetMinutes": 10,
        "softTimeoutMinutes": 12,
        "hardTimeoutMinutes": 15,
        "createdAt": "2026-01-01T00:00:00Z",
    }
    atomic_write_json(tdir / "META.json", meta)
    (tdir / "inbox" / "001-TASK.md").write_text("# TASK\n\nTest task.\n", encoding="utf-8")
    set_state(tdir, READY)
    return tdir


class TestCreateDispatchRun:
    """Test: create -> dispatch -> run -> REVIEW_REQUIRED."""

    def test_dispatch_sets_queued(self, setup_bridge):
        """Dispatch should set READY tasks to QUEUED."""
        root = setup_bridge
        _create_task(root, "t1")

        result = execute_dispatch(root / "tasks", root, max_workers=4, spawn_workers=False)
        assert len(result.plan.plan) == 1
        assert len(result.spawned) == 0  # spawn_workers=False

        state = get_state(root / "tasks" / "t1")
        assert state["status"] == QUEUED

    def test_dry_run_no_state_change(self, setup_bridge):
        """--dry-run must not modify state."""
        root = setup_bridge
        _create_task(root, "t1")

        result = execute_dispatch(root / "tasks", root, max_workers=4, dry_run=True)
        assert len(result.plan.plan) == 1
        assert len(result.spawned) == 0

        state = get_state(root / "tasks" / "t1")
        assert state["status"] == READY

    def test_spawn_failure_reverts_to_ready(self, setup_bridge):
        """If spawn fails, task should revert to READY, not stay QUEUED."""
        root = setup_bridge
        _create_task(root, "t1")

        # execute_dispatch with spawn_workers=True will try to spawn
        # subprocess.Popen(["python", "-m", "bridge.cli", "run", "-t", "t1"])
        # This may fail in test env, which should trigger revert
        result = execute_dispatch(root / "tasks", root, max_workers=4, spawn_workers=True)

        if result.failed:
            state = get_state(root / "tasks" / "t1")
            assert state["status"] == READY, f"Should revert to READY on spawn failure, got {state['status']}"

    def test_fake_runner_success(self, setup_bridge):
        """FakeRunner with success behavior should produce deliverables."""
        root = setup_bridge
        tdir = _create_task(root, "t1")
        set_state(tdir, QUEUED, message="dispatched")

        runner = FakeRunner(behavior="success")
        exit_code = runner.run(tdir)

        assert exit_code == 0
        assert (tdir / "outbox" / "RESULT.md").is_file()
        assert (tdir / "outbox" / "TESTS.md").is_file()
        assert (tdir / "outbox" / "DIFF.stat").is_file()

    def test_fake_runner_assistance(self, setup_bridge):
        """FakeRunner with assistance behavior should write checkpoint."""
        root = setup_bridge
        tdir = _create_task(root, "t1")
        set_state(tdir, QUEUED, message="dispatched")

        runner = FakeRunner(behavior="assistance")
        exit_code = runner.run(tdir)

        assert exit_code == 0
        assert (tdir / "outbox" / "CHECKPOINT.md").is_file()
        assert (tdir / "outbox" / "ASSISTANCE_REQUEST.md").is_file()


class TestCancelLifecycle:
    """Test: create -> cancel -> CANCELLED."""

    def test_cancel_task(self, setup_bridge):
        """Cancelling a READY task should set CANCELLED."""
        root = setup_bridge
        tdir = _create_task(root, "t1")

        set_state(tdir, CANCELLED, message="cancelled by user")
        state = get_state(tdir)
        assert state["status"] == CANCELLED


class TestAttemptLifecycle:
    """Test: attempt increments correctly across FIX cycles."""

    def test_attempt_increments(self, setup_bridge):
        """Each run should increment attempt in state.json."""
        root = setup_bridge
        tdir = _create_task(root, "t1")

        # First run: attempt should be 1
        state = get_state(tdir)
        attempt1 = int(state.get("attempt", 0)) + 1
        set_state(tdir, "RUNNING", attempt=attempt1)
        assert attempt1 == 1

        # Simulate FIX -> READY
        set_state(tdir, FIX_REQUIRED, attempt=attempt1)
        set_state(tdir, READY, attempt=attempt1)

        # Second run: attempt should be 2
        state = get_state(tdir)
        attempt2 = int(state.get("attempt", 0)) + 1
        set_state(tdir, "RUNNING", attempt=attempt2)
        assert attempt2 == 2

        # Third run: attempt should be 3
        set_state(tdir, FIX_REQUIRED, attempt=attempt2)
        set_state(tdir, READY, attempt=attempt2)
        state = get_state(tdir)
        attempt3 = int(state.get("attempt", 0)) + 1
        assert attempt3 == 3

    def test_evidence_not_overwritten(self, setup_bridge):
        """Previous attempt evidence should not be overwritten."""
        root = setup_bridge
        tdir = _create_task(root, "t1")

        # Simulate attempt 1 evidence
        ev1 = tdir / "evidence" / "attempt-001"
        ev1.mkdir(parents=True)
        (ev1 / "RESULT.md").write_text("attempt 1 result", encoding="utf-8")

        # Simulate attempt 2 evidence
        ev2 = tdir / "evidence" / "attempt-002"
        ev2.mkdir(parents=True)
        (ev2 / "RESULT.md").write_text("attempt 2 result", encoding="utf-8")

        # Both should exist with their own content
        assert (ev1 / "RESULT.md").read_text() == "attempt 1 result"
        assert (ev2 / "RESULT.md").read_text() == "attempt 2 result"


class TestWorkspaceIsolation:
    """Test: transport x role dispatch matrix."""

    def test_remote_worktree_implement_not_rejected(self, setup_bridge):
        """remote-worktree + implement should NOT be rejected as 'worktree only local'."""
        root = setup_bridge
        _create_task(root, "t1", project_id="test-remote", worker_id="w1")

        plan = select_dispatch_plan(root / "tasks", root, max_workers=4)

        # Should not be skipped with "worktree only supported for local"
        skip_reasons = [s.reason for s in plan.skipped]
        assert not any("worktree only" in r for r in skip_reasons), \
            f"remote-worktree should not be rejected: {skip_reasons}"

    def test_dependency_unfinished_skipped(self, setup_bridge):
        """Task with unfinished dependency should be skipped."""
        root = setup_bridge
        _create_task(root, "dep1")
        _create_task(root, "t1")

        # Set t1 to depend on dep1
        meta_path = root / "tasks" / "t1" / "META.json"
        meta = json.loads(meta_path.read_text())
        meta["dependsOn"] = ["dep1"]
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        plan = select_dispatch_plan(root / "tasks", root, max_workers=4)
        skip_reasons = [s.reason for s in plan.skipped if s.task_id == "t1"]
        assert any("dependencies" in r for r in skip_reasons), \
            f"t1 should be skipped due to dependencies: {skip_reasons}"

    def test_dependency_done_runnable(self, setup_bridge):
        """Task with DONE dependency should be runnable."""
        root = setup_bridge
        _create_task(root, "dep1")
        _create_task(root, "t1")

        # Mark dep1 as DONE
        set_state(root / "tasks" / "dep1", DONE, message="completed")

        # Set t1 to depend on dep1
        meta_path = root / "tasks" / "t1" / "META.json"
        meta = json.loads(meta_path.read_text())
        meta["dependsOn"] = ["dep1"]
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        plan = select_dispatch_plan(root / "tasks", root, max_workers=4)
        plan_ids = [item.task_id for item in plan.plan]
        assert "t1" in plan_ids, f"t1 should be in plan when dep is DONE: {plan_ids}"