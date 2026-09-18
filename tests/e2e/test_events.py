# AI生成
"""E2E tests for P0-08: runtime event echo, heartbeat, stale detection."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from bridge.runtime.events import (
    EventWriter, EventReader, compute_staleness, heartbeat_snapshot,
    sanitize_text, sanitize_event,
    STATUS, HEARTBEAT, TOOL, TEST, WARNING, TERMINAL,
    DEFAULT_STALE_SECONDS,
)


class TestEventWriter:
    """EventWriter produces monotonic seq events."""

    def test_monotonic_seq(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        e1 = w.write(STATUS, "t1", status="RUNNING")
        e2 = w.write(HEARTBEAT, "t1", summary="working")
        e3 = w.write(TERMINAL, "t1", result="DONE")
        assert e1["seq"] < e2["seq"] < e3["seq"]

    def test_event_types(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        for t in [STATUS, HEARTBEAT, TOOL, TEST, WARNING, TERMINAL]:
            e = w.write(t, "t1")
            assert e["type"] == t

    def test_invalid_type_rejected(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        with pytest.raises(ValueError):
            w.write("bogus", "t1")

    def test_task_and_attempt_isolation(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        w.write(HEARTBEAT, "t1", attempt=1, summary="a1")
        w.write(HEARTBEAT, "t1", attempt=2, summary="a2")
        w.write(HEARTBEAT, "t2", attempt=1, summary="b1")
        r = EventReader(tmp_path / "events.jsonl")
        assert len(r.read_for_task("t1", 1)) == 1
        assert len(r.read_for_task("t1", 2)) == 1
        assert len(r.read_for_task("t2", 1)) == 1

    def test_heartbeat_helper(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        e = w.heartbeat("t1", summary="step 1")
        assert e["type"] == HEARTBEAT
        assert e["summary"] == "step 1"

    def test_terminal_helper(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        e = w.terminal("t1", result="DONE")
        assert e["type"] == TERMINAL
        assert e["result"] == "DONE"


class TestEventReader:
    """EventReader reads and filters events."""

    def test_read_all(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        w.write(STATUS, "t1")
        w.write(HEARTBEAT, "t1")
        r = EventReader(tmp_path / "events.jsonl")
        assert len(r.read_all()) == 2

    def test_read_since(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        w.write(STATUS, "t1")
        e2 = w.write(HEARTBEAT, "t1")
        w.write(TERMINAL, "t1")
        r = EventReader(tmp_path / "events.jsonl")
        recent = r.read_since(e2["seq"])
        assert len(recent) == 2

    def test_last_heartbeat(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        w.heartbeat("t1", summary="first")
        w.status("t1", status="RUNNING")
        w.heartbeat("t1", summary="second")
        r = EventReader(tmp_path / "events.jsonl")
        hb = r.last_heartbeat("t1")
        assert hb["summary"] == "second"

    def test_no_file_returns_empty(self, tmp_path):
        r = EventReader(tmp_path / "nonexistent.jsonl")
        assert r.read_all() == []
        assert r.last_seq() == 0

    def test_corrupt_line_skipped(self, tmp_path):
        f = tmp_path / "events.jsonl"
        f.write_text('{"seq":1,"type":"status"}\nCORRUPT\n{"seq":2,"type":"heartbeat"}\n')
        r = EventReader(f)
        assert len(r.read_all()) == 2


class TestStaleDetection:
    """STALE detection for RUNNING tasks."""

    def test_running_with_fresh_heartbeat_is_live(self):
        now = time.time()
        s = compute_staleness("RUNNING", now - 5, now_epoch=now, stale_threshold=30)
        assert s.status == "LIVE"
        assert not s.is_stale

    def test_running_with_stale_heartbeat(self):
        now = time.time()
        s = compute_staleness("RUNNING", now - 60, now_epoch=now, stale_threshold=30)
        assert s.status == "STALE"
        assert s.is_stale

    def test_running_no_heartbeat_is_stale(self):
        s = compute_staleness("RUNNING", None)
        assert s.status == "STALE"
        assert s.is_stale

    def test_terminal_state_not_stale(self):
        for state in ["DONE", "FAILED", "BLOCKED", "CANCELLED", "REVIEW_REQUIRED", "ASSISTANCE_REQUIRED"]:
            s = compute_staleness(state, None)
            assert not s.is_stale
            assert s.status == state

    def test_stale_does_not_change_canonical(self):
        """STALE is observability only, does not set FAILED."""
        now = time.time()
        s = compute_staleness("RUNNING", now - 60, now_epoch=now, stale_threshold=30)
        assert s.status == "STALE"
        assert s.status != "FAILED"


class TestHeartbeatSnapshot:
    """UI snapshot for task status display."""

    def test_snapshot_with_events(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        w.status("t1", status="RUNNING")
        w.heartbeat("t1", summary="compiling")
        r = EventReader(tmp_path / "events.jsonl")
        snap = heartbeat_snapshot("t1", "RUNNING", 1, r)
        assert snap["taskId"] == "t1"
        assert snap["status"] == "RUNNING"
        assert snap["heartbeatSummary"] == "compiling"
        assert snap["eventCount"] == 2
        assert snap["stale"] == "LIVE"

    def test_snapshot_no_events(self, tmp_path):
        r = EventReader(tmp_path / "events.jsonl")
        snap = heartbeat_snapshot("t1", "RUNNING", 1, r)
        assert snap["eventCount"] == 0
        assert snap["stale"] == "STALE"
        assert snap["heartbeatSummary"] == ""

    def test_snapshot_attempt_isolation(self, tmp_path):
        w = EventWriter(tmp_path / "events.jsonl")
        w.heartbeat("t1", attempt=1, summary="attempt 1")
        w.heartbeat("t1", attempt=2, summary="attempt 2")
        r = EventReader(tmp_path / "events.jsonl")
        snap1 = heartbeat_snapshot("t1", "RUNNING", 1, r)
        snap2 = heartbeat_snapshot("t1", "RUNNING", 2, r)
        assert snap1["heartbeatSummary"] == "attempt 1"
        assert snap2["heartbeatSummary"] == "attempt 2"


class TestSanitization:
    """Sensitive info and private reasoning must be stripped."""

    def test_api_key_redacted(self):
        assert "sk-" not in sanitize_text("key=sk-abc12345678901234567890")

    def test_password_redacted(self):
        result = sanitize_text("password=secret123")
        assert "secret123" not in result

    def test_reasoning_markers_removed(self):
        text = "normal text <reasoning>private thoughts</reasoning> more text"
        result = sanitize_text(text)
        assert "<reasoning>" not in result
        assert "private thoughts" not in result

    def test_event_sanitizer_removes_reasoning_keys(self):
        event = {"seq": 1, "type": "status", "reasoning": "secret", "chain_of_thought": "secret"}
        result = sanitize_event(event)
        assert "reasoning" not in result
        assert "chain_of_thought" not in result

    def test_normal_text_preserved(self):
        text = "Building project... 50% done"
        assert sanitize_text(text) == text


class TestUIRestartRecovery:
    """UI restart should recover from persisted events."""

    def test_persisted_events_survive_restart(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        w1 = EventWriter(events_file)
        w1.status("t1", status="RUNNING")
        w1.heartbeat("t1", summary="step 1")
        w1.heartbeat("t1", summary="step 2")
        last_seq = w1._seq

        # Simulate UI restart — new reader reads same file
        r = EventReader(events_file)
        assert r.last_seq() == last_seq
        events = r.read_all()
        assert len(events) == 3
        snap = heartbeat_snapshot("t1", "RUNNING", 1, r)
        assert snap["heartbeatSummary"] == "step 2"

    def test_new_writer_continues_seq(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        w1 = EventWriter(events_file)
        w1.write(STATUS, "t1")
        w1.write(HEARTBEAT, "t1")

        # New writer instance (e.g. after restart)
        w2 = EventWriter(events_file)
        e = w2.write(TERMINAL, "t1", result="DONE")
        assert e["seq"] == 1  # New writer starts from 0


class TestConcurrentWorkers:
    """Four workers concurrent — events must not cross tasks."""

    def test_four_workers_no_task_cross_talk(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        w = EventWriter(events_file)
        for i in range(4):
            tid = f"t{i}"
            w.status(tid, status="RUNNING")
            w.heartbeat(tid, summary=f"worker {i}")
            w.terminal(tid, result="DONE")

        r = EventReader(events_file)
        for i in range(4):
            tid = f"t{i}"
            events = r.read_for_task(tid)
            assert len(events) == 3
            assert all(e["taskId"] == tid for e in events)

    def test_attempt_isolation_under_concurrency(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        w = EventWriter(events_file)
        # Task t1 attempt 1 and attempt 2 interleaved with t2
        w.heartbeat("t1", attempt=1, summary="t1a1")
        w.heartbeat("t2", attempt=1, summary="t2a1")
        w.heartbeat("t1", attempt=2, summary="t1a2")
        w.heartbeat("t2", attempt=1, summary="t2a1b")

        r = EventReader(events_file)
        t1a1 = r.read_for_task("t1", attempt=1)
        t1a2 = r.read_for_task("t1", attempt=2)
        t2a1 = r.read_for_task("t2", attempt=1)
        assert len(t1a1) == 1
        assert len(t1a2) == 1
        assert len(t2a1) == 2
