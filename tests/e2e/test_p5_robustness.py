"""P5 robustness tests: reconcile auto-repair, doctor stale detection, transport Popen path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def reconcile_bridge(tmp_path):
    """Create a bridge root with a stale RUNNING task and expired lease."""
    bridge = tmp_path / "bridge"
    (bridge / "tasks" / "stale-task").mkdir(parents=True)
    (bridge / "tasks" / "stale-task" / "outbox").mkdir()
    (bridge / "runtime" / "assignments").mkdir(parents=True)
    (bridge / "runtime" / "leases").mkdir(parents=True)

    # Task state: RUNNING with a dead process
    state = {
        "schemaVersion": 1,
        "taskId": "stale-task",
        "status": "RUNNING",
        "state": "RUNNING",
        "attempt": 1,
        "processId": 999999,
        "assignedWorkerId": "bus-w01-dev",
    }
    (bridge / "tasks" / "stale-task" / "state.json").write_text(json.dumps(state))

    # META.json
    meta = {"taskId": "stale-task", "projectId": "test", "role": "implement"}
    (bridge / "tasks" / "stale-task" / "META.json").write_text(json.dumps(meta))

    # Expired lease
    lease = {
        "leaseId": "lease-expired",
        "taskId": "stale-task",
        "workerId": "bus-w01-dev",
        "expiresAt": "2020-01-01T00:00:00+00:00",
        "heartbeatAt": "2020-01-01T00:00:00+00:00",
        "createdAt": "2020-01-01T00:00:00+00:00",
    }
    (bridge / "runtime" / "leases" / "lease-expired.json").write_text(json.dumps(lease))

    # Unfinished assignment
    asg = {
        "assignmentId": "asg-1",
        "taskId": "stale-task",
        "workerId": "bus-w01-dev",
        "leaseId": "lease-expired",
        "createdAt": "2020-01-01T00:00:00+00:00",
        "startedAt": None,
        "finishedAt": None,
    }
    (bridge / "runtime" / "assignments" / "asg-1.json").write_text(json.dumps(asg))

    return bridge


class TestReconcileAutoRepair:
    """P5-04: reconcile_assignments auto-repairs stuck RUNNING tasks."""

    def test_running_with_deliverables_becomes_review_required(self, reconcile_bridge):
        from bridge.scheduler.planner import reconcile_assignments
        from bridge.state import get_state

        # Add deliverables to outbox
        outbox = reconcile_bridge / "tasks" / "stale-task" / "outbox"
        (outbox / "RESULT.md").write_text("# RESULT")
        (outbox / "TESTS.md").write_text("# TESTS\n1 passed, 0 failed")

        count = reconcile_assignments(
            reconcile_bridge / "runtime" / "assignments",
            reconcile_bridge / "runtime" / "leases",
            reconcile_bridge / "tasks",
        )

        assert count == 1
        state = get_state(reconcile_bridge / "tasks" / "stale-task")
        status = state.get("status") or state.get("state", "")
        assert status == "REVIEW_REQUIRED"

    def test_running_without_deliverables_becomes_failed(self, reconcile_bridge):
        from bridge.scheduler.planner import reconcile_assignments
        from bridge.state import get_state

        # No deliverables in outbox
        count = reconcile_assignments(
            reconcile_bridge / "runtime" / "assignments",
            reconcile_bridge / "runtime" / "leases",
            reconcile_bridge / "tasks",
        )

        assert count == 1
        state = get_state(reconcile_bridge / "tasks" / "stale-task")
        status = state.get("status") or state.get("state", "")
        assert status == "FAILED"

    def test_assignment_finished_and_lease_released(self, reconcile_bridge):
        from bridge.scheduler.planner import reconcile_assignments

        (reconcile_bridge / "tasks" / "stale-task" / "outbox" / "RESULT.md").write_text("# RESULT")
        (reconcile_bridge / "tasks" / "stale-task" / "outbox" / "TESTS.md").write_text("# TESTS")

        reconcile_assignments(
            reconcile_bridge / "runtime" / "assignments",
            reconcile_bridge / "runtime" / "leases",
            reconcile_bridge / "tasks",
        )

        asg = json.loads((reconcile_bridge / "runtime" / "assignments" / "asg-1.json").read_text())
        assert asg["finishedAt"] is not None

        lease_path = reconcile_bridge / "runtime" / "leases" / "lease-expired.json"
        assert not lease_path.exists() or json.loads(lease_path.read_text()).get("releasedAt")


class TestDoctorStaleDetection:
    """P5-02: doctor detects RUNNING tasks with no live process."""

    def test_stale_running_task_detected(self, tmp_path):
        from bridge.doctor import check_stale_tasks

        bridge = tmp_path / "bridge"
        (bridge / "tasks" / "orphan-task").mkdir(parents=True)
        state = {
            "schemaVersion": 1,
            "taskId": "orphan-task",
            "status": "RUNNING",
            "state": "RUNNING",
            "processId": 999999,
        }
        (bridge / "tasks" / "orphan-task" / "state.json").write_text(json.dumps(state))

        result = check_stale_tasks(bridge)
        assert not result.passed
        assert "orphan-task" in result.detail

    def test_healthy_no_stale(self, tmp_path):
        from bridge.doctor import check_stale_tasks

        bridge = tmp_path / "bridge"
        (bridge / "tasks" / "done-task").mkdir(parents=True)
        state = {"status": "DONE", "state": "DONE"}
        (bridge / "tasks" / "done-task" / "state.json").write_text(json.dumps(state))

        result = check_stale_tasks(bridge)
        assert result.passed

    def test_running_with_live_process_not_stale(self, tmp_path):
        from bridge.doctor import check_stale_tasks

        bridge = tmp_path / "bridge"
        (bridge / "tasks" / "live-task").mkdir(parents=True)
        # Use current process PID
        state = {
            "status": "RUNNING",
            "state": "RUNNING",
            "processId": os.getpid(),
        }
        (bridge / "tasks" / "live-task" / "state.json").write_text(json.dumps(state))

        result = check_stale_tasks(bridge)
        assert result.passed


class TestTransportPopenPath:
    """P5-01: verify ssh transport Popen loop assigns result on normal completion."""

    def test_popen_normal_completion_assigns_result(self, tmp_path):
        """Simulate the Popen communicate loop with a fast-completing process."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "print('hello')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        poll_interval = 5
        result_assigned = False
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=poll_interval)
                result_assigned = True
                break
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate(timeout=10)
                break

        assert result_assigned, "result was never assigned on normal completion"
        assert stdout.strip() == "hello"

    def test_popen_timeout_triggers_kill(self, tmp_path):
        """Simulate hard timeout: process killed after timeout."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        timed_out = False
        result_assigned = False
        elapsed = 0
        poll_interval = 1
        timeout_seconds = 2

        while True:
            try:
                stdout, stderr = proc.communicate(timeout=poll_interval)
                result_assigned = True
                break
            except subprocess.TimeoutExpired:
                elapsed += poll_interval
                if elapsed >= timeout_seconds:
                    proc.kill()
                    proc.communicate(timeout=10)
                    timed_out = True
                    break

        assert timed_out, "hard timeout did not trigger"
        assert not result_assigned, "normal completion should not have happened"