# AI生成
"""Session management for runtime supervisor.

A session tracks a single execution attempt of a task on a worker.
Sessions are persisted to disk so they survive bridge restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..atomic import atomic_write_json, read_json_or_none
from ..core.ids import generate_session_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Session:
    session_id: str
    task_id: str
    worker_id: str
    assignment_id: str
    started_at: str = ""
    ended_at: str = ""
    status: str = "active"  # active, completed, failed, cancelled, timed_out
    exit_code: int | None = None
    pid: int | None = None
    attempt: int = 1
    log_path: str = ""

    def to_dict(self) -> dict:
        return {
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "workerId": self.worker_id,
            "assignmentId": self.assignment_id,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "status": self.status,
            "exitCode": self.exit_code,
            "pid": self.pid,
            "attempt": self.attempt,
            "logPath": self.log_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Session:
        return cls(
            session_id=d.get("sessionId", ""),
            task_id=d.get("taskId", ""),
            worker_id=d.get("workerId", ""),
            assignment_id=d.get("assignmentId", ""),
            started_at=d.get("startedAt", ""),
            ended_at=d.get("endedAt", ""),
            status=d.get("status", "active"),
            exit_code=d.get("exitCode"),
            pid=d.get("pid"),
            attempt=d.get("attempt", 1),
            log_path=d.get("logPath", ""),
        )


def create_session(
    runtime_dir: Path,
    task_id: str,
    worker_id: str,
    assignment_id: str,
    attempt: int = 1,
) -> Session:
    """Create and persist a new execution session."""
    session = Session(
        session_id=generate_session_id(task_id, attempt),
        task_id=task_id,
        worker_id=worker_id,
        assignment_id=assignment_id,
        started_at=_now_iso(),
        attempt=attempt,
    )

    sessions_dir = Path(runtime_dir) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(sessions_dir / f"{session.session_id}.json", session.to_dict())
    return session


def save_session(runtime_dir: Path, session: Session) -> None:
    """Update a session on disk."""
    sessions_dir = Path(runtime_dir) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(sessions_dir / f"{session.session_id}.json", session.to_dict())


def load_session(runtime_dir: Path, session_id: str) -> Session | None:
    """Load a session by ID."""
    path = Path(runtime_dir) / "sessions" / f"{session_id}.json"
    data = read_json_or_none(path)
    if data is None:
        return None
    return Session.from_dict(data)


def find_active_session(runtime_dir: Path, task_id: str) -> Session | None:
    """Find the active session for a task, if any."""
    sessions_dir = Path(runtime_dir) / "sessions"
    if not sessions_dir.exists():
        return None
    for p in sessions_dir.glob("*.json"):
        data = read_json_or_none(p)
        if data and data.get("taskId") == task_id and data.get("status") == "active":
            return Session.from_dict(data)
    return None


def end_session(
    runtime_dir: Path,
    session_id: str,
    status: str,
    exit_code: int | None = None,
) -> Session | None:
    """Mark a session as ended."""
    session = load_session(runtime_dir, session_id)
    if session is None:
        return None
    session.status = status
    session.ended_at = _now_iso()
    session.exit_code = exit_code
    save_session(runtime_dir, session)
    return session
