# AI生成
"""Event model for the bridge event stream."""

from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --- Event types ---
TASK_CREATED = "task.created"
TASK_STATE_CHANGED = "task.state_changed"
ASSIGNMENT_CREATED = "assignment.created"
ASSIGNMENT_STARTED = "assignment.started"
ASSIGNMENT_FINISHED = "assignment.finished"
WORKER_ONLINE = "worker.online"
WORKER_OFFLINE = "worker.offline"
RUNTIME_HEARTBEAT = "runtime.heartbeat"
RUNTIME_TIMEOUT = "runtime.timeout"
RUNTIME_CANCELLED = "runtime.cancelled"
REVIEW_REQUIRED = "review.required"
REVIEW_COMPLETED = "review.completed"
INTEGRATION_STARTED = "integration.started"
INTEGRATION_COMPLETED = "integration.completed"
POLICY_FAILED = "policy.failed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Event:
    event_id: str
    type: str
    timestamp: str = field(default_factory=_now_iso)
    task_id: str | None = None
    assignment_id: str | None = None
    worker_id: str | None = None
    payload: dict = field(default_factory=dict)
    seq: int | None = None

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        return cls(
            event_id=d.get("eventId", ""),
            type=d.get("type", ""),
            timestamp=d.get("timestamp", _now_iso()),
            task_id=d.get("taskId"),
            assignment_id=d.get("assignmentId"),
            worker_id=d.get("workerId"),
            payload=d.get("payload", {}),
            seq=d.get("seq"),
        )

    def to_dict(self) -> dict:
        d = {
            "eventId": self.event_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
        if self.task_id:
            d["taskId"] = self.task_id
        if self.assignment_id:
            d["assignmentId"] = self.assignment_id
        if self.worker_id:
            d["workerId"] = self.worker_id
        if self.seq is not None:
            d["seq"] = self.seq
        return d


class EventStore:
    """Append-only event log backed by a JSONL file.

    Supports file locking (EV-04) for safe concurrent writes and
    rotation (EV-05) to prevent unbounded growth.
    """

    def __init__(
        self,
        events_dir: Path,
        max_size_mb: int = 10,
        keep_files: int = 7,
    ):
        self._dir = Path(events_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._next_seq = self._read_max_seq() + 1
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._keep_files = keep_files

    def _read_max_seq(self) -> int:
        """Read the maximum seq from the events file, or 0 if none.

        Scans the file once on startup. Seq is monotonically increasing,
        so the max is on the last valid line, but we scan all lines to
        be robust against trailing partial writes.
        """
        path = self._dir / "events.jsonl"
        if not path.exists():
            return 0
        max_seq = 0
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    seq = d.get("seq")
                    if isinstance(seq, int) and seq > max_seq:
                        max_seq = seq
        except OSError:
            return 0
        return max_seq

    def append(self, event: Event) -> None:
        from ..core.ids import generate_event_id

        if not event.event_id:
            event.event_id = generate_event_id()

        event.seq = self._next_seq
        self._next_seq += 1

        line = json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
        path = self._dir / "events.jsonl"

        for attempt in range(3):
            try:
                with path.open("a", encoding="utf-8") as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
                    fcntl.flock(f, fcntl.LOCK_UN)
                break
            except BlockingIOError:
                time.sleep(0.1)
        else:
            with path.open("a", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(line)
                f.flush()
                fcntl.flock(f, fcntl.LOCK_UN)

        self.rotate_if_needed()

    def recent(self, limit: int = 50) -> list[Event]:
        path = self._dir / "events.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        events = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                events.append(Event.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
            if len(events) >= limit:
                break
        return list(reversed(events))

    def recent_after(self, seq: int) -> list[dict]:
        """Return events with seq > the given value, as dicts.

        Unlike recent(n) which is bounded by a count, this returns all
        events after the cursor, making it suitable for SSE tailing
        without the list-length-stuck-at-100 bug.
        """
        path = self._dir / "events.jsonl"
        if not path.exists():
            return []
        result: list[dict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_seq = d.get("seq")
                if isinstance(event_seq, int) and event_seq > seq:
                    result.append(d)
        return result
    def rotate_if_needed(self) -> bool:
        """Rotate events.jsonl if it exceeds max_size_mb.

        Renames current file to events.YYYYMMDD.jsonl, keeps last
        keep_files rotated files, deletes older ones. Returns True if
        rotation occurred.
        """
        path = self._dir / "events.jsonl"
        if not path.exists():
            return False
        if path.stat().st_size < self._max_size_bytes:
            return False

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        rotated = self._dir / f"events.{date_str}.jsonl"
        if rotated.exists():
            rotated.unlink()
        path.rename(rotated)

        rotated_files = sorted(
            self._dir.glob("events.*.jsonl"),
            key=lambda p: p.name,
        )
        while len(rotated_files) > self._keep_files:
            oldest = rotated_files.pop(0)
            oldest.unlink()

        return True
