"""Tests for DeadlineScheduler (SUP-01)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from bridge.supervision.model import SUPERVISION_OFFSETS_SECONDS, DeadlineEntry
from bridge.supervision.schedule import DeadlineScheduler


def test_start_task_schedules_6_deadlines():
    sched = DeadlineScheduler()
    sched.start_task("t1", 0.0, "2026-09-19T00:00:00+00:00")
    assert len(sched._heap) == 6
    offsets = sorted(e.due_monotonic for e in sched._heap)
    assert offsets == [float(o) for o in SUPERVISION_OFFSETS_SECONDS]


def test_pop_due_returns_in_order():
    sched = DeadlineScheduler()
    sched.start_task("t1", 0.0, "2026-09-19T00:00:00+00:00")
    last = -1.0
    for entry in sched.pop_due(now_monotonic=10000.0):
        assert entry.due_monotonic >= last
        last = entry.due_monotonic
    assert last == float(SUPERVISION_OFFSETS_SECONDS[-1])


def test_cancel_task_skips_future_entries():
    sched = DeadlineScheduler()
    sched.start_task("t1", 0.0, "2026-09-19T00:00:00+00:00")
    sched.cancel_task("t1")
    yielded = list(sched.pop_due(now_monotonic=10000.0))
    assert yielded == []


def test_cancel_does_not_remove_from_heap():
    sched = DeadlineScheduler()
    sched.start_task("t1", 0.0, "2026-09-19T00:00:00+00:00")
    size_before = len(sched._heap)
    sched.cancel_task("t1")
    size_after = len(sched._heap)
    assert size_before == size_after == 6


def test_two_tasks_independent_timers():
    sched = DeadlineScheduler()
    sched.start_task("t1", 0.0, "2026-09-19T00:00:00+00:00")
    sched.start_task("t2", 1000.0, "2026-09-19T00:16:40+00:00")
    assert len(sched._heap) == 12
    t1_entries = [e for e in sched._heap if e.task_id == "t1"]
    t2_entries = [e for e in sched._heap if e.task_id == "t2"]
    assert len(t1_entries) == 6
    assert len(t2_entries) == 6
    assert max(e.due_monotonic for e in t1_entries) < min(e.due_monotonic for e in t2_entries)


def test_next_due_at_returns_earliest():
    sched = DeadlineScheduler()
    sched.start_task("t1", 0.0, "2026-09-19T00:00:00+00:00")
    assert sched.next_due_at() == float(SUPERVISION_OFFSETS_SECONDS[0])
    sched.start_task("t2", 100.0, "2026-09-19T00:01:40+00:00")
    assert sched.next_due_at() == float(SUPERVISION_OFFSETS_SECONDS[0])


def test_retry_new_attempt_cancels_old():
    sched = DeadlineScheduler()
    sched.start_task("t1", 0.0, "2026-09-19T00:00:00+00:00")
    sched.start_task("t1", 5000.0, "2026-09-19T01:23:20+00:00")
    assert len(sched._heap) == 12
    yielded = list(sched.pop_due(now_monotonic=1000.0))
    assert yielded == []
    yielded_late = list(sched.pop_due(now_monotonic=100000.0))
    assert len(yielded_late) == 6
    assert all(e.task_id == "t1" for e in yielded_late)
    assert all(e.due_monotonic >= 5000.0 for e in yielded_late)
