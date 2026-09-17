# AI生成
"""Heartbeat tracking for runtime supervisor."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..atomic import atomic_write_json, read_json_or_none


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass
class HeartbeatInfo:
    task_id: str
    worker_id: str
    heartbeat_at: str = ""
    last_event_at: str = ""
    event_count: int = 0
    elapsed_seconds: float = 0.0
    token_usage: int = 0
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "taskId": self.task_id,
            "workerId": self.worker_id,
            "heartbeatAt": self.heartbeat_at,
            "lastEventAt": self.last_event_at,
            "eventCount": self.event_count,
            "elapsedSeconds": self.elapsed_seconds,
            "tokenUsage": self.token_usage,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> HeartbeatInfo:
        return cls(
            task_id=d.get("taskId", ""),
            worker_id=d.get("workerId", ""),
            heartbeat_at=d.get("heartbeatAt", ""),
            last_event_at=d.get("lastEventAt", ""),
            event_count=d.get("eventCount", 0),
            elapsed_seconds=d.get("elapsedSeconds", 0.0),
            token_usage=d.get("tokenUsage", 0),
            summary=d.get("summary", ""),
        )


def write_heartbeat(runtime_dir: Path, info: HeartbeatInfo) -> None:
    """Write heartbeat info to disk."""
    hb_dir = Path(runtime_dir) / "heartbeats"
    hb_dir.mkdir(parents=True, exist_ok=True)
    info.heartbeat_at = _iso(_now())
    path = hb_dir / f"{info.task_id}.json"
    atomic_write_json(path, info.to_dict())


def read_heartbeat(runtime_dir: Path, task_id: str) -> HeartbeatInfo | None:
    """Read heartbeat info for a task."""
    path = Path(runtime_dir) / "heartbeats" / f"{task_id}.json"
    data = read_json_or_none(path)
    if data is None:
        return None
    return HeartbeatInfo.from_dict(data)


def is_stale(runtime_dir: Path, task_id: str, stale_after_minutes: int = 5) -> bool:
    """Check if a task's heartbeat is stale."""
    info = read_heartbeat(runtime_dir, task_id)
    if info is None:
        return True  # No heartbeat = stale

    try:
        hb_time = datetime.fromisoformat(info.heartbeat_at)
        threshold = _now() - timedelta(minutes=stale_after_minutes)
        return hb_time < threshold
    except (ValueError, TypeError):
        return True


def remove_heartbeat(runtime_dir: Path, task_id: str) -> None:
    """Remove heartbeat file for a task."""
    path = Path(runtime_dir) / "heartbeats" / f"{task_id}.json"
    if path.exists():
        path.unlink()
