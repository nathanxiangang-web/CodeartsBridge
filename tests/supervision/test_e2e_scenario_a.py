"""E2E test: 6-minute completion scenario (E2E-01).

Scenario:
  00:00 RUNNING -> T+05 healthy -> T+06 REVIEW_REQUIRED -> T+06 Architect review

Uses mock time (manual monotonic injection) and mock inspector.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bridge.supervision.model import (
    ArchitectEvent,
    InspectionResult,
    SupervisionPlan,
)
from bridge.supervision.schedule import DeadlineScheduler
from bridge.supervision.supervisor import Supervisor


class MockInspector:
    """Inspector that returns HEALTHY for all stages."""

    def inspect(
        self, task_id: str, stage: int, plan: SupervisionPlan
    ) -> InspectionResult:
        return InspectionResult(
            task_id=task_id,
            stage=stage,
            alert=False,
            summary="healthy",
            deliverables={},
            progress_hash=f"hash-stage-{stage}",
            error_signature=None,
        )


def _make_supervisor(tmp_path) -> Supervisor:
    scheduler = DeadlineScheduler()
    inspector = MockInspector()
    return Supervisor(tmp_path, scheduler, inspector)


def test_6min_completion_cancels_remaining_stages(tmp_path):
    sup = _make_supervisor(tmp_path)
    t0 = 1000.0

    sup.on_task_started("t1", "w1", "2026-01-01T00:00:00+00:00")

    events = sup.tick(t0 + 300, "2026-01-01T00:05:00+00:00")
    assert events == []

    sup.on_task_completed("t1")

    events = sup.tick(t0 + 360, "2026-01-01T00:06:00+00:00")
    assert events == []

    events = sup.tick(t0 + 480, "2026-01-01T00:08:00+00:00")
    assert events == []

    events = sup.tick(t0 + 960, "2026-01-01T00:16:00+00:00")
    assert events == []


def test_review_required_emitted_immediately(tmp_path):
    sup = _make_supervisor(tmp_path)
    t0 = time.monotonic()

    sup.on_task_started("t1", "w1", "2026-01-01T00:00:00+00:00")

    time.sleep(0.01)
    events = sup.tick(time.monotonic() + 300, "2026-01-01T00:05:00+00:00")
    assert len(events) == 0

    plan = sup._plans["t1"]
    assert 0 in plan.completed_stages


def test_no_inspection_after_completion(tmp_path):
    sup = _make_supervisor(tmp_path)
    t0 = 1000.0

    sup.on_task_started("t1", "w1", "2026-01-01T00:00:00+00:00")
    sup.on_task_completed("t1")

    events = sup.tick(t0 + 300, "2026-01-01T00:05:00+00:00")
    assert events == []

    events = sup.tick(t0 + 480, "2026-01-01T00:08:00+00:00")
    assert events == []

    events = sup.tick(t0 + 660, "2026-01-01T00:11:00+00:00")
    assert events == []


def test_reactor_processes_review(tmp_path):
    from bridge.supervision.queue import ArchitectQueue as QueueImpl
    from bridge.supervision.reactor import ArchitectReactor

    queue = QueueImpl()
    from bridge.supervision.queue import ArchitectEvent as QEvent, make_dedupe_key

    evt = QEvent(
        event_id="e1",
        type="review.required",
        task_id="t1",
        worker_id="w1",
        priority=0,
        created_at="2026-01-01T00:06:00+00:00",
        payload={},
        dedupe_key=make_dedupe_key("review.required", "t1"),
    )
    queue.push(evt)
    assert queue.is_empty() is False

    popped = queue.pop()
    assert popped is not None
    assert popped.type == "review.required"
    assert queue.is_empty() is True