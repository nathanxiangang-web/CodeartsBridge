# AI生成
"""Tests for EventStore seq + append-only behavior (EV-01)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from bridge.core.events import Event, EventStore


def _make_event(type_: str = "task.created", task_id: str = "t1") -> Event:
    return Event(event_id="", type=type_, task_id=task_id, payload={"x": 1})


class TestEventStoreAppend:
    def test_append_does_not_rewrite_file(self, tmp_path):
        """append() must grow the file incrementally, not rewrite it."""
        store = EventStore(tmp_path / "events")
        path: Path = tmp_path / "events" / "events.jsonl"

        store.append(_make_event())
        size_after_first = path.stat().st_size
        assert size_after_first > 0

        store.append(_make_event())
        size_after_second = path.stat().st_size

        # If append rewrote the file, the second write would replace
        # the first line. With true append, the file grows by roughly
        # one line each time (the second line may differ slightly in
        # length due to seq/eventId, so we just assert it grew).
        assert size_after_second > size_after_first

        # Stronger check: the file must contain BOTH lines. A rewrite
        # would leave only the latest line.
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 2
        first = json.loads(lines[0])
        second = json.loads(lines[1])
        assert first["seq"] == 1
        assert second["seq"] == 2

    def test_seq_monotonic(self, tmp_path):
        """seq must increase by 1 for each append, starting at 1."""
        store = EventStore(tmp_path / "events")
        seqs = []
        for i in range(5):
            evt = _make_event()
            store.append(evt)
            seqs.append(evt.seq)
        assert seqs == [1, 2, 3, 4, 5]

    def test_seq_continues_after_reinit(self, tmp_path):
        """A new EventStore on an existing file must continue seq numbering."""
        store = EventStore(tmp_path / "events")
        for _ in range(3):
            store.append(_make_event())

        store2 = EventStore(tmp_path / "events")
        evt = _make_event()
        store2.append(evt)
        assert evt.seq == 4

    def test_recent_returns_events_with_seq(self, tmp_path):
        store = EventStore(tmp_path / "events")
        for _ in range(3):
            store.append(_make_event())
        recent = store.recent(10)
        assert len(recent) == 3
        assert [e.seq for e in recent] == [1, 2, 3]


class TestRecentAfter:
    def test_recent_after_empty(self, tmp_path):
        store = EventStore(tmp_path / "events")
        assert store.recent_after(0) == []

    def test_recent_after_returns_only_newer(self, tmp_path):
        store = EventStore(tmp_path / "events")
        for i in range(10):
            store.append(_make_event(task_id=f"t{i}"))

        # recent_after(5) returns events with seq > 5, i.e. seq 6..10
        result = store.recent_after(5)
        assert len(result) == 5
        assert [d["seq"] for d in result] == [6, 7, 8, 9, 10]

    def test_recent_after_zero_returns_all(self, tmp_path):
        store = EventStore(tmp_path / "events")
        for _ in range(5):
            store.append(_make_event())
        result = store.recent_after(0)
        assert len(result) == 5
        assert [d["seq"] for d in result] == [1, 2, 3, 4, 5]

    def test_recent_after_with_over_100_events(self, tmp_path):
        """recent_after must work correctly past 100 events.

        This is the SSE cursor bug scenario: recent(100) is bounded by
        count, so once >100 events exist, new events dont change
        len(recent(100)) and the SSE loop misses them. recent_after(seq)
        uses a seq cursor instead and must return all newer events.
        """
        store = EventStore(tmp_path / "events")
        for _ in range(150):
            store.append(_make_event())

        # Simulate SSE client that has seen up to seq=100.
        result = store.recent_after(100)
        assert len(result) == 50
        assert [d["seq"] for d in result] == list(range(101, 151))

        # Append more events; recent_after must pick them up.
        for _ in range(10):
            store.append(_make_event())
        result2 = store.recent_after(100)
        assert len(result2) == 60
        assert result2[-1]["seq"] == 160

    def test_recent_after_returns_dicts(self, tmp_path):
        """recent_after returns raw dicts (not Event objects)."""
        store = EventStore(tmp_path / "events")
        store.append(_make_event())
        result = store.recent_after(0)
        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert "seq" in result[0]
        assert "eventId" in result[0]
        assert result[0]["seq"] == 1
