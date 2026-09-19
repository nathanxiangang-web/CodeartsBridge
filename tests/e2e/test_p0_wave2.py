# AI生成
"""Legacy transport helper coverage and process supervisor tests."""

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
    """The legacy helper still documents SSH matching, but dispatch no longer blocks on it."""

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

    def test_explicit_worker_host_mismatch_no_longer_blocks_dispatch(self, tmp_path):
        """Local-First dispatch does not add a host-affinity gate."""
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
        assert [item.task_id for item in plan.plan] == ["t1"]
        assert not any("host mismatch" in s.reason for s in plan.skipped)

