"""Tests for CapacityMonitor (AR-05)."""

from __future__ import annotations

import time

from bridge.supervision.capacity import CapacityMonitor


def test_fires_when_workers_idle():
    cm = CapacityMonitor(cooldown_seconds=0)
    event = cm.check(
        enabled_workers=4, running_workers=1, ready_tasks=0,
        has_pending_work=True, project_id="p1",
    )
    assert event is not None
    assert event.event_type == "capacity.available"


def test_cooldown_prevents_spam():
    cm = CapacityMonitor(cooldown_seconds=60)
    e1 = cm.check(4, 1, 0, True, "p1")
    assert e1 is not None
    e2 = cm.check(4, 1, 0, True, "p1")
    assert e2 is None


def test_no_fire_when_tasks_ready():
    cm = CapacityMonitor(cooldown_seconds=0)
    event = cm.check(4, 1, 5, True, "p1")
    assert event is None


def test_no_fire_when_no_pending_work():
    cm = CapacityMonitor(cooldown_seconds=0)
    event = cm.check(4, 1, 0, False, "p1")
    assert event is None


def test_no_fire_when_all_workers_busy():
    cm = CapacityMonitor(cooldown_seconds=0)
    event = cm.check(4, 4, 0, True, "p1")
    assert event is None


def test_precreated_tasks_respect_dependsOn():
    cm = CapacityMonitor(cooldown_seconds=0)
    event = cm.check(4, 1, 3, True, "p1")
    assert event is None