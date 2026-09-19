"""Tests for hard_collect (SUP-04) and cleanup (SUP-05)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from bridge.supervision.supervisor import Supervisor
from bridge.supervision.schedule import DeadlineScheduler
from bridge.supervision.inspector import TaskInspector


def _make_supervisor(tmp_path) -> Supervisor:
    scheduler = DeadlineScheduler()
    inspector = TaskInspector(tmp_path)
    return Supervisor(tmp_path, scheduler, inspector)


def _write_state(task_dir: Path, state: dict) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "state.json").write_text(json.dumps(state))


def test_complete_delivery_to_review(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    _write_state(task_dir, {"status": "RUNNING", "processId": None})
    (task_dir / "RESULT.md").write_text("done")
    (task_dir / "TESTS.md").write_text("pass")
    sup = _make_supervisor(tmp_path)
    result = sup.hard_collect("t1", tmp_path)
    assert result == "REVIEW_REQUIRED"


def test_partial_work_to_assistance(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    _write_state(task_dir, {"status": "RUNNING", "processId": None})
    (task_dir / "ASSISTANCE_REQUEST.md").write_text("need help")
    sup = _make_supervisor(tmp_path)
    result = sup.hard_collect("t1", tmp_path)
    assert result == "ASSISTANCE_REQUIRED"


def test_no_output_to_failed(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    _write_state(task_dir, {"status": "RUNNING", "processId": None})
    sup = _make_supervisor(tmp_path)
    result = sup.hard_collect("t1", tmp_path)
    assert result == "FAILED"


def test_grace_period_then_kill(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    pid = os.getpid()
    _write_state(task_dir, {"status": "RUNNING", "processId": 999999})
    sup = _make_supervisor(tmp_path)
    result = sup.hard_collect("t1", tmp_path, grace_seconds=0)
    assert result == "FAILED"


def test_does_not_extend_task(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    _write_state(task_dir, {"status": "RUNNING", "processId": None})
    (task_dir / "RESULT.md").write_text("done")
    (task_dir / "TESTS.md").write_text("pass")
    sup = _make_supervisor(tmp_path)
    r1 = sup.hard_collect("t1", tmp_path)
    r2 = sup.hard_collect("t1", tmp_path)
    assert r1 == r2 == "REVIEW_REQUIRED"


def test_cleanup_orphan_running_with_deliverables(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    _write_state(task_dir, {"status": "RUNNING", "processId": None})
    (task_dir / "RESULT.md").write_text("done")
    (task_dir / "TESTS.md").write_text("pass")
    sup = _make_supervisor(tmp_path)
    result = sup.cleanup("t1", tmp_path)
    assert result == "REVIEW_REQUIRED"


def test_cleanup_orphan_running_no_output(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    _write_state(task_dir, {"status": "RUNNING", "processId": None})
    sup = _make_supervisor(tmp_path)
    result = sup.cleanup("t1", tmp_path)
    assert result == "FAILED"


def test_cleanup_non_running_no_change(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    _write_state(task_dir, {"status": "DONE", "processId": None})
    sup = _make_supervisor(tmp_path)
    result = sup.cleanup("t1", tmp_path)
    assert result == "DONE"


def test_cleanup_kills_process_if_alive(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    _write_state(task_dir, {"status": "RUNNING", "processId": 999999})
    sup = _make_supervisor(tmp_path)
    result = sup.cleanup("t1", tmp_path)
    assert result in ("FAILED", "ASSISTANCE_REQUIRED", "REVIEW_REQUIRED")


def test_hard_collect_saves_salvage(tmp_path):
    task_dir = tmp_path / "tasks" / "t1"
    _write_state(task_dir, {"status": "RUNNING", "processId": None})
    (task_dir / "RESULT.md").write_text("done")
    sup = _make_supervisor(tmp_path)
    sup.hard_collect("t1", tmp_path)
    assert (task_dir / "salvage" / "deliverables.json").exists()