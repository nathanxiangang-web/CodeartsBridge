"""Tests for ArchitectQueue priority + dedupe behavior (AR-01)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from bridge.supervision.queue import ArchitectEvent, ArchitectQueue, make_dedupe_key


def _make_event(
    event_id: str = "e1",
    type: str = "review.required",
    task_id: str | None = "t1",
    worker_id: str | None = "w1",
    priority: int = 0,
    created_at: str = "2026-09-19T00:00:00+00:00",
    payload: dict | None = None,
    dedupe_key: str | None = None,
    attempt: int = 0,
) -> ArchitectEvent:
    return ArchitectEvent(
        event_id=event_id,
        type=type,
        task_id=task_id,
        worker_id=worker_id,
        priority=priority,
        created_at=created_at,
        payload=payload or {},
        dedupe_key=dedupe_key or make_dedupe_key(type, task_id, attempt),
        attempt=attempt,
    )


def test_push_pop_priority_order():
    """P0 events come out before P1."""
    q = ArchitectQueue()
    q.push(_make_event(event_id="e1", priority=1, dedupe_key="a:1"))
    q.push(_make_event(event_id="e2", priority=0, dedupe_key="b:1"))
    first = q.pop()
    second = q.pop()
    assert first is not None and first.event_id == "e2"
    assert second is not None and second.event_id == "e1"


def test_dedupe_same_key_not_added():
    """Same dedupe_key does not add duplicate."""
    q = ArchitectQueue()
    added1 = q.push(_make_event(event_id="e1", priority=1, dedupe_key="k1"))
    added2 = q.push(_make_event(event_id="e2", priority=1, dedupe_key="k1"))
    assert added1 is True
    assert added2 is False
    assert q.size() == 1


def test_dedupe_upgrades_priority():
    """Higher priority duplicate upgrades existing."""
    q = ArchitectQueue()
    q.push(_make_event(event_id="e1", priority=2, dedupe_key="k1", created_at="2026-09-19T00:00:00+00:00"))
    q.push(_make_event(event_id="e2", priority=0, dedupe_key="k1", created_at="2026-09-19T00:01:00+00:00"))
    assert q.size() == 1
    evt = q.pop()
    assert evt is not None
    assert evt.priority == 0
    assert evt.created_at == "2026-09-19T00:01:00+00:00"


def test_pop_returns_none_when_empty():
    """Pop on an empty queue returns None."""
    q = ArchitectQueue()
    assert q.pop() is None


def test_has_pending_for_task():
    """has_pending returns True for tasks with queued events, False otherwise."""
    q = ArchitectQueue()
    q.push(_make_event(event_id="e1", task_id="t1", dedupe_key="k1"))
    q.push(_make_event(event_id="e2", task_id="t2", dedupe_key="k2"))
    assert q.has_pending("t1") is True
    assert q.has_pending("t2") is True
    assert q.has_pending("t3") is False


def test_multiple_event_types_ordered():
    """Mix of P0/P1/P2/P3 comes out in priority order."""
    q = ArchitectQueue()
    q.push(_make_event(event_id="p3", priority=3, dedupe_key="k3"))
    q.push(_make_event(event_id="p1", priority=1, dedupe_key="k1"))
    q.push(_make_event(event_id="p0", priority=0, dedupe_key="k0"))
    q.push(_make_event(event_id="p2", priority=2, dedupe_key="k2"))
    order = []
    while not q.is_empty():
        evt = q.pop()
        assert evt is not None
        order.append(evt.priority)
    assert order == [0, 1, 2, 3]


def test_dedupe_key_format():
    """Verify key format is type:task_id:attempt."""
    key = make_dedupe_key("review.required", "t1", 0)
    assert key == "review.required:t1:0"

    # Events with the canonical key format dedupe correctly.
    q = ArchitectQueue()
    e1 = _make_event(type="assistance.required", task_id="t1", attempt=0, priority=0)
    e2 = _make_event(type="assistance.required", task_id="t1", attempt=0, priority=1)
    assert e1.dedupe_key == "assistance.required:t1:0"
    assert e2.dedupe_key == e1.dedupe_key
    assert q.push(e1) is True
    assert q.push(e2) is False


def test_peek_does_not_remove():
    """Peek returns the next event without removing it."""
    q = ArchitectQueue()
    q.push(_make_event(event_id="e1", priority=1, dedupe_key="k1"))
    q.push(_make_event(event_id="e2", priority=0, dedupe_key="k2"))
    top = q.peek()
    assert top is not None and top.event_id == "e2"
    assert q.size() == 2
    popped = q.pop()
    assert popped is not None and popped.event_id == "e2"


def test_is_empty_and_size():
    """is_empty and size track the logical queue state."""
    q = ArchitectQueue()
    assert q.is_empty() is True
    assert q.size() == 0
    q.push(_make_event(event_id="e1", dedupe_key="k1"))
    assert q.is_empty() is False
    assert q.size() == 1
    q.pop()
    assert q.is_empty() is True
    assert q.size() == 0
