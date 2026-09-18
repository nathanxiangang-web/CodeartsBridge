# AI生成
"""Runtime event echo, heartbeat, and stale detection.

P0-08: Reliable runtime event stream for UI feedback.
Events are written to events.jsonl with monotonic seq.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

STATUS = "status"
HEARTBEAT = "heartbeat"
TOOL = "tool"
TEST = "test"
WARNING = "warning"
TERMINAL = "terminal"

VALID_TYPES = {STATUS, HEARTBEAT, TOOL, TEST, WARNING, TERMINAL}

DEFAULT_STALE_SECONDS = 30.0

_REASONING_MARKERS = ["<think>", "</think>", "<reasoning>", "</reasoning>", "chain_of_thought"]
_SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"password\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=]\s*\S+", re.IGNORECASE),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_epoch() -> float:
    return time.time()


def sanitize_text(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL)
    for marker in _REASONING_MARKERS:
        if marker in text:
            text = text.replace(marker, "")
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def sanitize_event(event: dict) -> dict:
    sanitized = dict(event)
    for key in ("message", "summary", "detail", "output"):
        if key in sanitized and isinstance(sanitized[key], str):
            sanitized[key] = sanitize_text(sanitized[key])
    for key in list(sanitized.keys()):
        kl = key.lower()
        if "reasoning" in kl or "private" in kl or "chain" in kl:
            del sanitized[key]
    return sanitized


class EventWriter:
    """Writes events to events.jsonl with monotonic seq."""

    def __init__(self, events_file: str | Path):
        self.events_file = Path(events_file)
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def write(self, event_type: str, task_id: str, attempt: int = 1, **fields) -> dict:
        if event_type not in VALID_TYPES:
            raise ValueError(f"invalid event type: {event_type}")
        event = {
            "seq": self._next_seq(),
            "type": event_type,
            "taskId": task_id,
            "attempt": attempt,
            "timestamp": _now_iso(),
            "epoch": _now_epoch(),
            **fields,
        }
        event = sanitize_event(event)
        try:
            with open(self.events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as e:
            warning = {
                "seq": self._next_seq(),
                "type": WARNING,
                "taskId": task_id,
                "attempt": attempt,
                "timestamp": _now_iso(),
                "epoch": _now_epoch(),
                "message": f"event file write failed: {e}",
            }
            try:
                with open(self.events_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(warning, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return event

    def heartbeat(self, task_id: str, attempt: int = 1, summary: str = "") -> dict:
        return self.write(HEARTBEAT, task_id, attempt, summary=summary)

    def status(self, task_id: str, attempt: int = 1, status: str = "", **extra) -> dict:
        return self.write(STATUS, task_id, attempt, status=status, **extra)

    def terminal(self, task_id: str, attempt: int = 1, result: str = "", **extra) -> dict:
        return self.write(TERMINAL, task_id, attempt, result=result, **extra)


class EventReader:
    """Reads events from events.jsonl."""

    def __init__(self, events_file: str | Path):
        self.events_file = Path(events_file)

    def exists(self) -> bool:
        return self.events_file.is_file()

    def read_all(self) -> list[dict]:
        if not self.exists():
            return []
        events = []
        with open(self.events_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return events

    def read_since(self, min_seq: int = 0) -> list[dict]:
        return [e for e in self.read_all() if e.get("seq", 0) >= min_seq]

    def read_for_task(self, task_id: str, attempt: int | None = None) -> list[dict]:
        events = []
        for e in self.read_all():
            if e.get("taskId") != task_id:
                continue
            if attempt is not None and e.get("attempt") != attempt:
                continue
            events.append(e)
        return events

    def last_seq(self) -> int:
        events = self.read_all()
        return max((e.get("seq", 0) for e in events), default=0)

    def last_heartbeat(self, task_id: str, attempt: int = 1) -> dict | None:
        heartbeats = [
            e for e in self.read_for_task(task_id, attempt)
            if e.get("type") == HEARTBEAT
        ]
        return heartbeats[-1] if heartbeats else None


@dataclass
class StaleStatus:
    is_stale: bool
    last_heartbeat_age: float
    status: str


def compute_staleness(
    task_status: str,
    last_heartbeat_epoch: float | None,
    now_epoch: float | None = None,
    stale_threshold: float = DEFAULT_STALE_SECONDS,
) -> StaleStatus:
    terminal_states = {"DONE", "FAILED", "BLOCKED", "CANCELLED", "REVIEW_REQUIRED", "ASSISTANCE_REQUIRED"}
    if task_status in terminal_states:
        return StaleStatus(is_stale=False, last_heartbeat_age=0.0, status=task_status)
    if task_status != "RUNNING":
        return StaleStatus(is_stale=False, last_heartbeat_age=0.0, status=task_status)
    now = now_epoch if now_epoch is not None else _now_epoch()
    if last_heartbeat_epoch is None:
        return StaleStatus(is_stale=True, last_heartbeat_age=float("inf"), status="STALE")
    age = now - last_heartbeat_epoch
    if age > stale_threshold:
        return StaleStatus(is_stale=True, last_heartbeat_age=age, status="STALE")
    return StaleStatus(is_stale=False, last_heartbeat_age=age, status="LIVE")


def heartbeat_snapshot(
    task_id: str,
    task_status: str,
    attempt: int,
    reader: EventReader,
    stale_threshold: float = DEFAULT_STALE_SECONDS,
) -> dict:
    events = reader.read_for_task(task_id, attempt)
    last_event = events[-1] if events else None
    last_hb = reader.last_heartbeat(task_id, attempt)
    last_hb_epoch = last_hb.get("epoch") if last_hb else None
    stale = compute_staleness(task_status, last_hb_epoch, stale_threshold=stale_threshold)
    return {
        "taskId": task_id,
        "status": task_status,
        "attempt": attempt,
        "stale": stale.status,
        "lastEventSeq": last_event.get("seq", 0) if last_event else 0,
        "lastEventAt": last_event.get("timestamp") if last_event else None,
        "lastHeartbeatAt": last_hb.get("timestamp") if last_hb else None,
        "heartbeatSummary": last_hb.get("summary", "") if last_hb else "",
        "eventCount": len(events),
    }
