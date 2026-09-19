"""Tests for TaskInspector (SUP-03)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from bridge.supervision.inspector import TaskInspector
from bridge.supervision.model import SupervisionPlan


def _make_plan(task_id: str = "t1") -> SupervisionPlan:
    return SupervisionPlan(
        task_id=task_id,
        worker_id="w1",
        running_at="2026-01-01T00:00:00+00:00",
        next_stage=0,
        next_due_at=None,
        completed_stages=[],
    )


def _write_state(bridge_root: Path, task_id: str, state: dict) -> None:
    d = bridge_root / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(state))


def _write_heartbeat(bridge_root: Path, task_id: str, ts: float) -> None:
    d = bridge_root / "runtime" / "heartbeats"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task_id}.json").write_text(json.dumps({"timestamp": ts}))


def test_inspect_normal_task(tmp_path):
    _write_state(tmp_path, "t1", {"status": "RUNNING", "deliverables": {}})
    _write_heartbeat(tmp_path, "t1", time.time())
    insp = TaskInspector(tmp_path)
    result = insp.inspect("t1", 0, _make_plan())
    assert result.alert is False
    assert result.task_id == "t1"
    assert result.stage == 0


def test_inspect_missing_state_alerts(tmp_path):
    _write_heartbeat(tmp_path, "t1", time.time())
    insp = TaskInspector(tmp_path)
    result = insp.inspect("t1", 0, _make_plan())
    assert result.alert is True
    assert "state missing" in result.summary


def test_inspect_failed_task_alerts(tmp_path):
    _write_state(tmp_path, "t1", {"status": "FAILED"})
    _write_heartbeat(tmp_path, "t1", time.time())
    insp = TaskInspector(tmp_path)
    result = insp.inspect("t1", 0, _make_plan())
    assert result.alert is True
    assert "FAILED" in result.summary


def test_inspect_stale_heartbeat_alerts_at_stage2(tmp_path):
    _write_state(tmp_path, "t1", {"status": "RUNNING"})
    _write_heartbeat(tmp_path, "t1", time.time() - 999)
    insp = TaskInspector(tmp_path, stale_seconds=10)
    result = insp.inspect("t1", 2, _make_plan())
    assert result.alert is True
    assert "heartbeat stale" in result.summary


def test_inspect_progress_hash_changes(tmp_path):
    _write_state(tmp_path, "t1", {"status": "RUNNING"})
    _write_heartbeat(tmp_path, "t1", time.time())
    insp = TaskInspector(tmp_path)
    r1 = insp.inspect("t1", 0, _make_plan())
    deliverables_dir = tmp_path / "tasks" / "t1" / "deliverables"
    deliverables_dir.mkdir(exist_ok=True)
    (deliverables_dir / "RESULT.md").write_text("done")
    r2 = insp.inspect("t1", 1, _make_plan())
    assert r1.progress_hash is None
    assert r2.progress_hash is not None


def test_inspect_error_signature(tmp_path):
    _write_state(tmp_path, "t1", {"status": "RUNNING"})
    _write_heartbeat(tmp_path, "t1", time.time())
    (tmp_path / "tasks" / "t1").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tasks" / "t1" / "error.log").write_text("Error: something failed")
    insp = TaskInspector(tmp_path)
    result = insp.inspect("t1", 0, _make_plan())
    assert result.error_signature is not None