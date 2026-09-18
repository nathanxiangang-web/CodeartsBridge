# AI生成
"""E2E tests for P0-06 soft timeout and P0-09 extended scenarios."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from bridge.atomic import atomic_write_json
from bridge.state import get_state, set_state, READY, RUNNING, ASSISTANCE_REQUIRED, CANCELLED
from bridge.runtime.timeout import (
    TimeoutConfig, TimeoutStatus, check_timeout,
    handle_soft_timeout, handle_hard_timeout, from_task_meta,
)
from bridge.result_classifier import (
    WorkerResult, classify_result,
    REVIEW_REQUIRED, BLOCKED, ASSISTANCE_REQUIRED as RC_ASSIST,
    CANCELLED as RC_CANCEL, FAILED,
)
from fake_runner import FakeRunner


def _create_task(bridge_root, task_id, project_id="test-local", worker_id="w1"):
    tdir = bridge_root / "tasks" / task_id
    (tdir / "inbox").mkdir(parents=True)
    (tdir / "outbox").mkdir()
    (tdir / "evidence").mkdir()
    meta = {
        "schemaVersion": 1, "taskId": task_id, "projectId": project_id,
        "workerId": worker_id, "role": "implement", "taskKind": "implementation",
        "targetMinutes": 5, "softTimeoutMinutes": 8, "hardTimeoutMinutes": 10,
        "createdAt": "2026-01-01T00:00:00Z",
    }
    atomic_write_json(tdir / "META.json", meta)
    (tdir / "inbox" / "001-TASK.md").write_text("# TASK\n\nTest.\n", encoding="utf-8")
    set_state(tdir, READY)
    return tdir


class TestSoftTimeout:
    """P0-06: soft timeout checkpoint and assistance delivery."""

    def test_soft_timeout_not_exceeded(self, tmp_path):
        """Before soft timeout, no action needed."""
        tdir = tmp_path / "task"
        tdir.mkdir()
        started = datetime.now(timezone.utc)
        config = TimeoutConfig(soft_timeout_minutes=10, hard_timeout_minutes=20)
        status = check_timeout(started, config)

        action = handle_soft_timeout(tdir, status)
        assert action is None

    def test_soft_timeout_requests_checkpoint(self, tmp_path):
        """When soft timeout exceeded, checkpoint is requested."""
        tdir = tmp_path / "task"
        (tdir / "inbox").mkdir(parents=True)
        (tdir / "outbox").mkdir()
        started = datetime.now(timezone.utc) - timedelta(minutes=15)
        config = TimeoutConfig(soft_timeout_minutes=10, hard_timeout_minutes=20)
        status = check_timeout(started, config)

        action = handle_soft_timeout(tdir, status)
        assert action == "CHECKPOINT_REQUESTED"
        assert (tdir / "inbox" / "CHECKPOINT_REQUEST.md").is_file()

    def test_soft_timeout_with_checkpoint_assistance(self, tmp_path):
        """If CHECKPOINT + ASSISTANCE_REQUEST exist, return ASSISTANCE_REQUIRED."""
        tdir = tmp_path / "task"
        (tdir / "inbox").mkdir(parents=True)
        (tdir / "outbox").mkdir()
        (tdir / "outbox" / "CHECKPOINT.md").write_text("checkpoint")
        (tdir / "outbox" / "ASSISTANCE_REQUEST.md").write_text("need help")

        started = datetime.now(timezone.utc) - timedelta(minutes=15)
        config = TimeoutConfig(soft_timeout_minutes=10, hard_timeout_minutes=20)
        status = check_timeout(started, config)

        action = handle_soft_timeout(tdir, status)
        assert action == "ASSISTANCE_REQUIRED"

    def test_soft_timeout_does_not_fail(self, tmp_path):
        """Soft timeout should NOT set FAILED state."""
        tdir = tmp_path / "task"
        (tdir / "inbox").mkdir(parents=True)
        (tdir / "outbox").mkdir()
        started = datetime.now(timezone.utc) - timedelta(minutes=15)
        config = TimeoutConfig(soft_timeout_minutes=10, hard_timeout_minutes=20)
        status = check_timeout(started, config)

        action = handle_soft_timeout(tdir, status)
        assert action != "FAILED"
        assert action is not None  # Some action was taken

    def test_hard_timeout_exceeded(self, tmp_path):
        """Hard timeout should return True for force kill."""
        tdir = tmp_path / "task"
        tdir.mkdir()
        started = datetime.now(timezone.utc) - timedelta(minutes=25)
        config = TimeoutConfig(soft_timeout_minutes=10, hard_timeout_minutes=20)
        status = check_timeout(started, config)

        should_kill = handle_hard_timeout(tdir, status)
        assert should_kill is True

    def test_hard_timeout_not_exceeded(self, tmp_path):
        """Before hard timeout, no kill needed."""
        tdir = tmp_path / "task"
        tdir.mkdir()
        started = datetime.now(timezone.utc)
        config = TimeoutConfig(soft_timeout_minutes=10, hard_timeout_minutes=20)
        status = check_timeout(started, config)

        should_kill = handle_hard_timeout(tdir, status)
        assert should_kill is False

    def test_from_task_meta_v1_compat(self):
        """from_task_meta should work with v1 META format."""
        meta = {
            "targetMinutes": 5,
            "softTimeoutMinutes": 8,
            "hardTimeoutMinutes": 10,
        }
        config = from_task_meta(meta)
        assert config.soft_timeout_minutes == 8
        assert config.hard_timeout_minutes == 10
        assert config.target_minutes == 5

    def test_soft_timeout_idempotent(self, tmp_path):
        """Requesting checkpoint twice should not duplicate."""
        tdir = tmp_path / "task"
        (tdir / "inbox").mkdir(parents=True)
        (tdir / "outbox").mkdir()
        started = datetime.now(timezone.utc) - timedelta(minutes=15)
        config = TimeoutConfig(soft_timeout_minutes=10, hard_timeout_minutes=20)
        status = check_timeout(started, config)

        # First call requests checkpoint
        action1 = handle_soft_timeout(tdir, status, already_requested=False)
        assert action1 == "CHECKPOINT_REQUESTED"

        # Second call with already_requested=True should not re-request
        action2 = handle_soft_timeout(tdir, status, already_requested=True)
        assert action2 is None


class TestSoftTimeoutE2E:
    """P0-09: E2E test for create → soft timeout → ASSISTANCE_REQUIRED."""

    def test_create_soft_timeout_assistance(self, tmp_path):
        """Full flow: create task → run → soft timeout → checkpoint → ASSISTANCE_REQUIRED."""
        tdir = tmp_path / "task"
        (tdir / "inbox").mkdir(parents=True)
        (tdir / "outbox").mkdir()
        (tdir / "evidence").mkdir()

        meta = {
            "schemaVersion": 1, "taskId": "t1", "projectId": "p1",
            "workerId": "w1", "role": "implement",
            "targetMinutes": 1, "softTimeoutMinutes": 2, "hardTimeoutMinutes": 5,
        }
        atomic_write_json(tdir / "META.json", meta)
        set_state(tdir, RUNNING, message="running")

        # Simulate soft timeout
        config = from_task_meta(meta)
        started = datetime.now(timezone.utc) - timedelta(minutes=3)
        status = check_timeout(started, config)
        assert status.soft_exceeded

        # Worker produces checkpoint via FakeRunner
        runner = FakeRunner(behavior="assistance")
        runner.run(tdir)

        # Classify result
        action = handle_soft_timeout(tdir, status)
        assert action == "ASSISTANCE_REQUIRED"

        # State should be set to ASSISTANCE_REQUIRED
        set_state(tdir, ASSISTANCE_REQUIRED, message="soft timeout + assistance request")
        state = get_state(tdir)
        assert state["status"] == ASSISTANCE_REQUIRED


class TestResultClassifierIntegration:
    """P0-09: verify result classifier integrates with timeout and cancel."""

    def test_cancelled_takes_priority_over_timeout(self):
        """Cancel should take priority over timeout in classifier."""
        r = WorkerResult(exit_code=1, cancelled=True, timed_out=True)
        result = classify_result(r)
        assert result.state == RC_CANCEL

    def test_assistance_from_checkpoint(self):
        """Checkpoint + assistance request → ASSISTANCE_REQUIRED."""
        r = WorkerResult(exit_code=0, has_checkpoint=True, has_assistance_request=True)
        result = classify_result(r)
        assert result.state == RC_ASSIST

    def test_timeout_without_cancel_is_retryable(self):
        """Timeout without cancel → RETRYABLE."""
        r = WorkerResult(exit_code=1, timed_out=True)
        result = classify_result(r)
        assert result.state == "RETRYABLE"