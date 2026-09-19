"""Tests for Supervisor (SUP-02)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from bridge.supervision.model import (
    ArchitectEvent,
    InspectionResult,
    SupervisionPlan,
)
from bridge.supervision.schedule import DeadlineScheduler
from bridge.supervision.supervisor import Supervisor


class FakeInspector:
    """Test double for Inspector protocol."""

    def __init__(self, alert_stages: set[int] | None = None):
        self.alert_stages = alert_stages or set()
        self.calls: list[tuple[str, int]] = []

    def inspect(
        self, task_id: str, stage: int, plan: SupervisionPlan
    ) -> InspectionResult:
        self.calls.append((task_id, stage))
        return InspectionResult(
            task_id=task_id,
            stage=stage,
            alert=stage in self.alert_stages,
            summary=f"stage-{stage}",
        )


def _make_supervisor(tmp_path: Path, inspector=None):
    bridge_root = tmp_path / "bridge"
    scheduler = DeadlineScheduler()
    if inspector is None:
        inspector = FakeInspector()
    sup = Supervisor(bridge_root, scheduler, inspector)
    return sup, scheduler, inspector


def test_on_task_started_creates_and_persists_plan(tmp_path):
    sup, sched, inspector = _make_supervisor(tmp_path)
    sup.on_task_started("t1", "w1", "2026-09-19T00:00:00+00:00")

    plan_file = tmp_path / "bridge" / "runtime" / "supervision" / "tasks" / "t1.json"
    assert plan_file.exists()
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    assert data["taskId"] == "t1"
    assert data["workerId"] == "w1"
    assert data["runningAt"] == "2026-09-19T00:00:00+00:00"
    assert data["completedStages"] == []
    assert data["cancelled"] is False

    assert len(sched._heap) == 6


def test_on_task_completed_cancels_deadlines(tmp_path):
    sup, sched, inspector = _make_supervisor(tmp_path)
    sup.on_task_started("t1", "w1", "2026-09-19T00:00:00+00:00")
    assert sched.next_due_at() is not None

    sup.on_task_completed("t1")

    yielded = list(sched.pop_due(now_monotonic=999999.0))
    assert yielded == []

    plan_file = tmp_path / "bridge" / "runtime" / "supervision" / "tasks" / "t1.json"
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    assert data["cancelled"] is True


def test_tick_normal_inspection_returns_no_events(tmp_path):
    inspector = FakeInspector(alert_stages=set())
    sup, sched, _ = _make_supervisor(tmp_path, inspector)
    sup.on_task_started("t1", "w1", "2026-09-19T00:00:00+00:00")

    events = sup.tick(now_monotonic=999999.0, now_wallclock="2026-09-19T00:20:00+00:00")
    assert events == []
    assert len(inspector.calls) == 6


def test_tick_alert_returns_architect_event(tmp_path):
    inspector = FakeInspector(alert_stages={2})
    sup, sched, _ = _make_supervisor(tmp_path, inspector)
    sup.on_task_started("t1", "w1", "2026-09-19T00:00:00+00:00")

    events = sup.tick(now_monotonic=999999.0, now_wallclock="2026-09-19T00:20:00+00:00")

    alert_events = [e for e in events if e.event_type == "alert"]
    assert len(alert_events) == 1
    assert alert_events[0].task_id == "t1"
    assert alert_events[0].stage == 2


def test_persist_and_recover_plan(tmp_path):
    sup, sched, inspector = _make_supervisor(tmp_path)
    sup.on_task_started("t1", "w1", "2026-09-19T00:00:00+00:00")

    sup2, sched2, inspector2 = _make_supervisor(tmp_path)
    sup2.recover()

    assert "t1" in sup2._plans
    plan = sup2._plans["t1"]
    assert plan.task_id == "t1"
    assert plan.worker_id == "w1"
    assert plan.running_at == "2026-09-19T00:00:00+00:00"


def test_recovery_skips_completed_stages(tmp_path):
    sup, sched, inspector = _make_supervisor(tmp_path)
    sup.on_task_started("t1", "w1", "2026-09-19T00:00:00+00:00")

    plan = sup._plans["t1"]
    plan.completed_stages = [0, 1, 2, 3, 4, 5]
    sup._persist_plan(plan)

    sup2, sched2, inspector2 = _make_supervisor(tmp_path)
    sup2.recover()

    assert inspector2.calls == []


def test_running_at_is_write_once(tmp_path):
    sup, sched, inspector = _make_supervisor(tmp_path)
    sup.on_task_started("t1", "w1", "2026-09-19T00:00:00+00:00")

    sup.on_task_started("t1", "w2", "2026-09-19T00:05:00+00:00")

    plan_file = tmp_path / "bridge" / "runtime" / "supervision" / "tasks" / "t1.json"
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    assert data["runningAt"] == "2026-09-19T00:00:00+00:00"
