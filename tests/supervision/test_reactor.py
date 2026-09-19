from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from bridge.core.events import Event
from bridge.state import (
    ASSISTANCE_REQUIRED,
    DONE,
    REVIEW_REQUIRED,
    set_state,
)
from bridge.supervision.reactor import ArchitectReactor


class FakeQueue:
    def __init__(self, events=None):
        self._events = list(events or [])

    def pop(self):
        if self._events:
            return self._events.pop(0)
        return None

    def is_empty(self):
        return len(self._events) == 0

    def push(self, event):
        self._events.append(event)


_event_counter = [0]


def _make_event(event_type, task_id="t1", worker_id=None, payload=None):
    _event_counter[0] += 1
    return Event(
        event_id="evt-%d" % _event_counter[0],
        type=event_type,
        task_id=task_id,
        worker_id=worker_id,
        payload=payload or {},
    )


def _setup_task(tmp_path, task_id="t1", state=None):
    bridge_root = tmp_path / "bridge"
    task_dir = bridge_root / "tasks" / task_id
    task_dir.mkdir(parents=True)
    if state is not None:
        set_state(task_dir, state)
    return bridge_root, task_dir


def test_review_required_triggers_review(tmp_path):
    bridge_root, task_dir = _setup_task(tmp_path, state=REVIEW_REQUIRED)
    calls = []

    def mock_review(task_id, bridge_root):
        calls.append((task_id, bridge_root))
        return "PASS"

    queue = FakeQueue([_make_event("review.required")])
    reactor = ArchitectReactor(queue, bridge_root, review_task_fn=mock_review)
    processed = reactor.process_next()
    assert processed is True
    assert len(calls) == 1
    assert calls[0][0] == "t1"


def test_skips_if_state_not_review_required(tmp_path):
    bridge_root, task_dir = _setup_task(tmp_path, state=DONE)
    calls = []

    def mock_review(task_id, bridge_root):
        calls.append(task_id)
        return "PASS"

    queue = FakeQueue([_make_event("review.required")])
    reactor = ArchitectReactor(queue, bridge_root, review_task_fn=mock_review)
    processed = reactor.process_next()
    assert processed is True
    assert len(calls) == 0
    skip_actions = [a for a in reactor.actions if a.get("action") == "skip"]
    assert len(skip_actions) == 1
    assert skip_actions[0]["reason"] == "state_mismatch"


def test_review_lock_prevents_duplicate(tmp_path):
    bridge_root, task_dir = _setup_task(tmp_path, state=REVIEW_REQUIRED)
    calls = []

    def mock_review(task_id, bridge_root):
        calls.append(task_id)
        return "PASS"

    queue = FakeQueue([_make_event("review.required")])
    reactor = ArchitectReactor(queue, bridge_root, review_task_fn=mock_review)
    reactor._review_lock.add("t1")
    processed = reactor.process_next()
    assert processed is True
    assert len(calls) == 0
    skip_actions = [a for a in reactor.actions if a.get("action") == "skip"]
    assert len(skip_actions) == 1
    assert skip_actions[0]["reason"] == "review_locked"


def test_supervision_alert_prepares_context(tmp_path):
    bridge_root, task_dir = _setup_task(tmp_path, state=REVIEW_REQUIRED)
    payload = {
        "elapsed": 120,
        "last_progress": "wrote reactor.py",
        "repeated_errors": 2,
        "diff_state": "modified",
        "outbox_state": "partial",
    }
    queue = FakeQueue(
        [_make_event("supervision.alert", worker_id="w01", payload=payload)]
    )
    reactor = ArchitectReactor(queue, bridge_root)
    processed = reactor.process_next()
    assert processed is True
    ctx = reactor.last_alert_context
    assert ctx is not None
    expected_keys = {
        "task_id",
        "worker_id",
        "elapsed",
        "last_progress",
        "repeated_errors",
        "diff_state",
        "outbox_state",
    }
    assert set(ctx.keys()) == expected_keys
    assert ctx["task_id"] == "t1"
    assert ctx["worker_id"] == "w01"
    assert ctx["elapsed"] == 120
    assert "session_log" not in ctx


def test_assistance_required_analyzes(tmp_path):
    bridge_root, task_dir = _setup_task(tmp_path, state=ASSISTANCE_REQUIRED)
    calls = []

    def mock_analyzer(event, bridge_root):
        calls.append(event.task_id)
        return "split"

    queue = FakeQueue([_make_event("assistance.required")])
    reactor = ArchitectReactor(queue, bridge_root, assistance_analyzer=mock_analyzer)
    processed = reactor.process_next()
    assert processed is True
    assert len(calls) == 1
    assert calls[0] == "t1"
    assert reactor.last_assistance_decision == "split"


def test_process_batch_limit(tmp_path):
    bridge_root = tmp_path / "bridge"
    bridge_root.mkdir()
    events = [
        _make_event("capacity.available", task_id=None) for _ in range(5)
    ]
    queue = FakeQueue(events)
    reactor = ArchitectReactor(queue, bridge_root)
    count = reactor.process_batch(max_events=3)
    assert count == 3
    assert not reactor.is_idle()


def test_is_idle_when_queue_empty(tmp_path):
    bridge_root = tmp_path / "bridge"
    bridge_root.mkdir()
    queue = FakeQueue()
    reactor = ArchitectReactor(queue, bridge_root)
    assert reactor.is_idle() is True
    reactor._queue.push(_make_event("capacity.available", task_id=None))
    assert reactor.is_idle() is False
