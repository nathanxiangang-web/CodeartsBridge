# AI生成
"""E2E tests for P2-04 conflict detection and resolution."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from bridge.conflict import (
    detect_conflict,
    auto_rebase,
    handle_conflict,
    ConflictResult,
    RebaseResult,
    ConflictResolution,
    CONFLICT,
)
from bridge.state import get_state, set_state, DONE, READY


@pytest.fixture
def conflict_bridge(tmp_path):
    bridge = tmp_path / "bridge"
    (bridge / "tasks").mkdir(parents=True)
    (bridge / "runtime").mkdir(parents=True)
    (bridge / "projects").mkdir(parents=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    (bridge / "projects.json").write_text(json.dumps({
        "schemaVersion": 1,
        "defaults": {},
        "projects": [{
            "id": "test-proj",
            "transport": "local",
            "projectRoot": str(repo),
        }]
    }))

    return bridge, repo


def _create_task(bridge: Path, task_id: str, commit_sha: str = "abc123"):
    task_dir = bridge / "tasks" / task_id
    (task_dir / "inbox").mkdir(parents=True)
    (task_dir / "outbox").mkdir(parents=True)
    (task_dir / "META.json").write_text(json.dumps({
        "schemaVersion": 2,
        "taskId": task_id,
        "projectId": "test-proj",
        "workerId": "w1",
        "role": "implement",
        "dependsOn": [],
        "priority": 0,
        "createdAt": "2026-01-01T00:00:00Z",
        "execution": {"preferredWorker": None, "excludedWorkers": []},
        "review": {"required": True, "independentWorker": True},
    }))
    (task_dir / "state.json").write_text(json.dumps({
        "state": DONE,
        "status": DONE,
        "schemaVersion": 1,
        "taskId": task_id,
        "attempt": 1,
        "updatedAt": "2026-01-01T00:00:00Z",
        "message": "done",
        "processId": None,
        "exitCode": 0,
        "commitSha": commit_sha,
    }))


class TestConflictDetection:
    def test_no_conflict_disjoint_files(self, conflict_bridge):
        bridge, repo = conflict_bridge
        (repo / "a.txt").write_text("A\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "main change"], cwd=repo, check=True)

        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
        ).stdout.strip()

        _create_task(bridge, "t1", sha)
        cr = detect_conflict("t1", bridge)
        assert not cr.conflict

    def test_conflict_overlapping_files(self, conflict_bridge):
        bridge, repo = conflict_bridge

        (repo / "shared.txt").write_text("task\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "task change"], cwd=repo, check=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
        ).stdout.strip()

        (repo / "shared.txt").write_text("main\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "main change"], cwd=repo, check=True)

        _create_task(bridge, "t1", sha)
        cr = detect_conflict("t1", bridge)
        assert cr.conflict
        assert "shared.txt" in cr.conflicting_files

    def test_missing_meta(self, conflict_bridge):
        bridge, repo = conflict_bridge
        cr = detect_conflict("nonexistent", bridge)
        assert not cr.conflict
        assert "META" in cr.context or "not found" in cr.context

    def test_no_commit_sha(self, conflict_bridge):
        bridge, repo = conflict_bridge
        task_dir = bridge / "tasks" / "t1"
        (task_dir / "inbox").mkdir(parents=True)
        (task_dir / "META.json").write_text(json.dumps({"taskId": "t1", "projectId": "test-proj"}))
        (task_dir / "state.json").write_text(json.dumps({"state": DONE}))
        cr = detect_conflict("t1", bridge)
        assert "no commit" in cr.context.lower()


class TestAutoRebase:
    def test_rebase_success_disjoint(self, conflict_bridge):
        bridge, repo = conflict_bridge
        (repo / "a.txt").write_text("A\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        _create_task(bridge, "t1", sha)
        rr = auto_rebase("t1", bridge)
        assert rr.success

    def test_rebase_fails_on_conflict(self, conflict_bridge):
        bridge, repo = conflict_bridge

        (repo / "shared.txt").write_text("task\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "task change"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

        (repo / "shared.txt").write_text("main\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "main change"], cwd=repo, check=True)

        _create_task(bridge, "t1", sha)
        rr = auto_rebase("t1", bridge)
        assert not rr.success

    def test_rebase_no_commit(self, conflict_bridge):
        bridge, repo = conflict_bridge
        task_dir = bridge / "tasks" / "t1"
        (task_dir / "inbox").mkdir(parents=True)
        (task_dir / "META.json").write_text(json.dumps({"taskId": "t1", "projectId": "test-proj"}))
        (task_dir / "state.json").write_text(json.dumps({"state": DONE}))
        rr = auto_rebase("t1", bridge)
        assert not rr.success


class TestHandleConflict:
    def test_marks_conflict_state(self, conflict_bridge):
        bridge, repo = conflict_bridge

        (repo / "shared.txt").write_text("task\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "task change"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

        (repo / "shared.txt").write_text("main\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "main change"], cwd=repo, check=True)

        _create_task(bridge, "t1", sha)
        resolution = handle_conflict("t1", bridge)
        assert resolution.marked_conflict
        state = get_state(bridge / "tasks" / "t1")
        assert state.get("state") == CONFLICT

    def test_no_conflict_no_action(self, conflict_bridge):
        bridge, repo = conflict_bridge
        (repo / "a.txt").write_text("A\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        _create_task(bridge, "t1", sha)

        resolution = handle_conflict("t1", bridge)
        assert not resolution.marked_conflict

    def test_writes_conflict_md(self, conflict_bridge):
        bridge, repo = conflict_bridge

        (repo / "shared.txt").write_text("task\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "task change"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

        (repo / "shared.txt").write_text("main\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "main change"], cwd=repo, check=True)

        _create_task(bridge, "t1", sha)
        handle_conflict("t1", bridge)
        conflict_md = bridge / "tasks" / "t1" / "outbox" / "CONFLICT.md"
        assert conflict_md.exists()
        assert "t1" in conflict_md.read_text()

    def test_writes_event(self, conflict_bridge):
        bridge, repo = conflict_bridge

        (repo / "shared.txt").write_text("task\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "task change"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

        (repo / "shared.txt").write_text("main\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "main change"], cwd=repo, check=True)

        _create_task(bridge, "t1", sha)
        resolution = handle_conflict("t1", bridge)
        assert resolution.event_written
        events = (bridge / "runtime" / "events.jsonl").read_text()
        assert "CONFLICT" in events
        assert "t1" in events