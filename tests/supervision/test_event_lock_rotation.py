"""Tests for EventStore file locking (EV-04) and rotation (EV-05)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from bridge.core.events import Event, EventStore


def _make_event(seq=None) -> Event:
    return Event(event_id="evt-1", type="task.created", task_id="t1", seq=seq)


def test_concurrent_appends_no_corruption(tmp_path):
    store = EventStore(tmp_path / "events")
    errors: list[Exception] = []

    def writer(start: int) -> None:
        try:
            for i in range(20):
                store.append(Event(
                    event_id=f"evt-{start}-{i}",
                    type="task.created",
                    task_id=f"t{start}",
                ))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    path = tmp_path / "events" / "events.jsonl"
    lines = [l for l in path.read_text().strip().split("\n") if l.strip()]
    for line in lines:
        json.loads(line)
    assert len(lines) == 80


def test_lock_released_after_write(tmp_path):
    store = EventStore(tmp_path / "events")
    store.append(_make_event())
    path = tmp_path / "events" / "events.jsonl"
    import fcntl
    with path.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)


def test_retry_on_contention(tmp_path):
    store1 = EventStore(tmp_path / "events")
    store2 = EventStore(tmp_path / "events")
    store1.append(_make_event())
    store2.append(Event(event_id="evt-2", type="task.created", task_id="t2"))
    path = tmp_path / "events" / "events.jsonl"
    lines = [l for l in path.read_text().strip().split("\n") if l.strip()]
    assert len(lines) == 2


def test_no_rotation_under_limit(tmp_path):
    store = EventStore(tmp_path / "events", max_size_mb=10)
    store.append(_make_event())
    assert store.rotate_if_needed() is False
    assert (tmp_path / "events" / "events.jsonl").exists()


def test_rotation_at_limit(tmp_path):
    store = EventStore(tmp_path / "events", max_size_mb=1, keep_files=3)
    big_payload = {"x": "A" * 500000}
    for i in range(5):
        store.append(Event(
            event_id=f"evt-{i}",
            type="task.created",
            task_id="t1",
            payload=big_payload,
        ))
    rotated = list((tmp_path / "events").glob("events.*.jsonl"))
    assert len(rotated) >= 1


def test_old_rotated_files_deleted(tmp_path):
    store = EventStore(tmp_path / "events", max_size_mb=1, keep_files=2)
    big_payload = {"x": "A" * 500000}
    for i in range(20):
        store.append(Event(
            event_id=f"evt-{i}",
            type="task.created",
            task_id="t1",
            payload=big_payload,
        ))
    rotated = sorted((tmp_path / "events").glob("events.*.jsonl"))
    assert len(rotated) <= 2


def test_rotation_preserves_events(tmp_path):
    store = EventStore(tmp_path / "events", max_size_mb=1, keep_files=5)
    for i in range(5):
        store.append(Event(
            event_id=f"evt-{i}",
            type="task.created",
            task_id="t1",
        ))
    big_payload = {"x": "A" * 500000}
    for i in range(5):
        store.append(Event(
            event_id=f"big-{i}",
            type="task.created",
            task_id="t1",
            payload=big_payload,
        ))
    all_files = [tmp_path / "events" / "events.jsonl"]
    all_files.extend(sorted((tmp_path / "events").glob("events.*.jsonl")))
    total = 0
    for f in all_files:
        if f.exists():
            for line in f.read_text().strip().split("\n"):
                if line.strip():
                    json.loads(line)
                    total += 1
    assert total == 10