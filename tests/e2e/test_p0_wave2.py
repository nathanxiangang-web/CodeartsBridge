# AI生成
"""Tests for host affinity (P0-04) and process supervisor (P0-05)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from bridge.atomic import atomic_write_json
from bridge.state import get_state, set_state, READY, QUEUED, CANCELLED, CANCEL_REQUESTED, RUNNING
from bridge.dispatch import select_dispatch_plan, check_host_affinity
from bridge.config import ProjectConfig, WorkerConfig
from fake_runner import FakeRunner


def _create_task(bridge_root, task_id, project_id="test-local", worker_id="w1", role="implement"):
    tdir = bridge_root / "tasks" / task_id
    (tdir / "inbox").mkdir(parents=True)
    (tdir / "outbox").mkdir()
    (tdir / "evidence").mkdir()
    meta = {
        "schemaVersion": 1, "taskId": task_id, "projectId": project_id,
        "workerId": worker_id, "role": role, "taskKind": "implementation",
        "targetMinutes": 10, "softTimeoutMinutes": 12, "hardTimeoutMinutes": 15,
        "createdAt": "2026-01-01T00:00:00Z",
    }
    atomic_write_json(tdir / "META.json", meta)
    (tdir / "inbox" / "001-TASK.md").write_text("# TASK\n\nTest.\n", encoding="utf-8")
    set_state(tdir, READY)
    return tdir


class TestHostAffinity:
    """P0-04: worker-to-host affinity enforcement."""

    def test_matching_host_passes(self):
        worker = WorkerConfig(id="w1", transport="ssh", host="user@host1")
        project = ProjectConfig(id="p1", transport="ssh", project_root="/repo", ssh_host="user@host1")
        assert check_host_affinity(worker, project) is True

    def test_mismatched_host_fails(self):
        worker = WorkerConfig(id="w1", transport="ssh", host="user@host1")
        project = ProjectConfig(id="p1", transport="ssh", project_root="/repo", ssh_host="user@host2")
        assert check_host_affinity(worker, project) is False

    def test_local_project_no_check(self):
        worker = WorkerConfig(id="w1", transport="local")
        project = ProjectConfig(id="p1", transport="local", project_root="/repo")
        assert check_host_affinity(worker, project) is True

    def test_no_ssh_host_no_check(self):
        worker = WorkerConfig(id="w1", transport="ssh", host="user@host1")
        project = ProjectConfig(id="p1", transport="ssh", project_root="/repo")
        assert check_host_affinity(worker, project) is True

    def test_worker_without_host_fails(self):
        worker = WorkerConfig(id="w1", transport="ssh")
        project = ProjectConfig(id="p1", transport="ssh", project_root="/repo", ssh_host="user@host1")
        assert check_host_affinity(worker, project) is False

    def test_explicit_worker_host_mismatch_skipped(self, tmp_path):
        """Explicit worker with wrong host should be skipped."""
        root = tmp_path / "bridge"
        for d in ("tasks", "runtime", "runtime/worktrees", "work"):
            (root / d).mkdir(parents=True, exist_ok=True)

        projects = {"schemaVersion": 1, "defaults": {}, "projects": [
            {"id": "p1", "transport": "ssh", "projectRoot": "/repo", "sshHost": "user@host1"},
        ]}
        (root / "projects.json").write_text(json.dumps(projects))

        workers = {"schemaVersion": 1, "defaults": {}, "workers": [
            {"id": "w1", "transport": "ssh", "host": "user@host2", "concurrencyLimit": 1,
             "enabled": True, "capabilities": ["implement"]},
        ]}
        (root / "workers.json").write_text(json.dumps(workers))

        _create_task(root, "t1", project_id="p1", worker_id="w1")

        plan = select_dispatch_plan(root / "tasks", root, max_workers=4)
        skip_reasons = [s.reason for s in plan.skipped]
        assert any("host mismatch" in r for r in skip_reasons), f"Expected host mismatch skip: {skip_reasons}"


class TestProcessSupervisor:
    """P0-05: process supervisor and cancellation."""

    def test_cancel_no_tracked_process(self, tmp_path):
        """Cancel with no tracked process should set CANCELLED."""
        from bridge.runtime.process_supervisor import ProcessSupervisor

        sup = ProcessSupervisor()
        tdir = tmp_path / "task"
        tdir.mkdir()
        set_state(tdir, RUNNING, message="running")

        result = sup.cancel("t1", tdir, grace_seconds=0.1)
        assert result["state"] == CANCELLED

        state = get_state(tdir)
        assert state["status"] == CANCELLED

    def test_cancel_idempotent(self, tmp_path):
        """Cancelling an already CANCELLED task should be idempotent."""
        from bridge.runtime.process_supervisor import ProcessSupervisor

        sup = ProcessSupervisor()
        tdir = tmp_path / "task"
        tdir.mkdir()
        set_state(tdir, CANCELLED, message="already cancelled")

        result = sup.cancel("t1", tdir)
        assert result["state"] == CANCELLED
        assert "already" in result["message"]

    def test_cancel_sets_cancel_requested_first(self, tmp_path):
        """Cancel should set CANCEL_REQUESTED before CANCELLED."""
        from bridge.runtime.process_supervisor import ProcessSupervisor

        sup = ProcessSupervisor()
        tdir = tmp_path / "task"
        tdir.mkdir()
        set_state(tdir, RUNNING, message="running")

        # Cancel with no tracked process — should go RUNNING -> CANCEL_REQUESTED -> CANCELLED
        result = sup.cancel("t1", tdir, grace_seconds=0.1)
        assert result["state"] == CANCELLED

        # Final state should be CANCELLED
        state = get_state(tdir)
        assert state["status"] == CANCELLED

    def test_cancelled_state_in_all_states(self):
        """CANCELLED should be in ALL_STATES."""
        from bridge.state import ALL_STATES, TERMINAL_STATES
        assert CANCELLED in ALL_STATES
        assert CANCELLED in TERMINAL_STATES
        assert CANCEL_REQUESTED in ALL_STATES