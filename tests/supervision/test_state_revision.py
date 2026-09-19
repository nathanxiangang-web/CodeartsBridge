"""Tests for state revision field (ST-01)."""

from __future__ import annotations

import json
from pathlib import Path

from bridge.state import set_state, get_state, READY, QUEUED, RUNNING


def test_revision_starts_at_1(tmp_path):
    task_dir = tmp_path / "t1"
    task_dir.mkdir()
    state = set_state(task_dir, READY)
    assert state["revision"] == 1


def test_revision_increments_on_state_change(tmp_path):
    task_dir = tmp_path / "t1"
    task_dir.mkdir()
    set_state(task_dir, READY)
    state = set_state(task_dir, QUEUED)
    assert state["revision"] == 2
    state = set_state(task_dir, RUNNING, assigned_worker_id="w1")
    assert state["revision"] == 3


def test_old_task_defaults_to_0(tmp_path):
    task_dir = tmp_path / "t1"
    task_dir.mkdir()
    (task_dir / "state.json").write_text(json.dumps({
        "taskId": "t1",
        "status": "READY",
        "state": "READY",
    }))
    state = get_state(task_dir)
    assert state.get("revision", 0) == 0


def test_revision_after_loading_old_task(tmp_path):
    task_dir = tmp_path / "t1"
    task_dir.mkdir()
    (task_dir / "state.json").write_text(json.dumps({
        "taskId": "t1",
        "status": "READY",
        "state": "READY",
    }))
    state = set_state(task_dir, QUEUED)
    assert state["revision"] == 1