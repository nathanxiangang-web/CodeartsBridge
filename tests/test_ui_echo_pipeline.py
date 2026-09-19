"""Regression tests for the read-only UI echo pipeline."""
from __future__ import annotations

from pathlib import Path

from bridge.agent.artifacts import collect_artifacts
from bridge.api.server import _summarize_agent_events


def test_agent_event_summary_exposes_timer_and_counts(monkeypatch):
    monkeypatch.setattr("bridge.api.server.time.time", lambda: 105.0)
    data = _summarize_agent_events([
        {"id": "a", "time": 100.0, "type": "started", "text": "start"},
        {"id": "b", "time": 101.0, "type": "reasoning", "text": "think"},
        {"id": "c", "time": 102.0, "type": "tool", "text": "read main.py"},
    ])
    assert data["startTime"] == 100000
    assert data["elapsed"] == 5
    assert data["reasoningCount"] == 1
    assert data["toolCount"] == 1
    assert data["eventCount"] == 3
    assert data["events"][1]["timestamp"] == 101.0


def test_completed_agent_event_summary_stops_timer():
    data = _summarize_agent_events([
        {"id": "a", "time": 100.0, "type": "started", "text": "start"},
        {"id": "b", "time": 104.0, "type": "completed", "text": "done"},
    ])
    assert data["elapsed"] == 4


def test_session_log_is_exported_as_agent_artifact(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "session.log").write_text('{"type":"reasoning"}\n', encoding="utf-8")
    artifacts = collect_artifacts(job_dir)
    names = {item["name"] for item in artifacts["files"]}
    assert "session.log" in names


def test_frontend_sse_uses_real_bridge_endpoint():
    root = Path(__file__).resolve().parent.parent
    source = (root / "src" / "bridge" / "web" / "js" / "events.js").read_text(encoding="utf-8")
    assert "EventSource('/api/events')" in source
    assert "/api/events/stream" not in source
