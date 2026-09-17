# AI生成
"""Task state machine.

Mirrors PowerShell Get-State / Set-State with merge-update semantics.
State file is always at <task_dir>/state.json.

State transitions:
    READY -> QUEUED -> STARTING -> RUNNING -> REVIEW_REQUIRED -> DONE
                                      |                      ^
                                      +-> BLOCKED            |
                                      +-> ASSISTANCE_REQUIRED|
                                      +-> AUTH_REQUIRED      |
                                      +-> RETRYABLE          |
                                      +-> FAILED             |
    REVIEW_REQUIRED -> FIX_REQUIRED -> RUNNING
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, read_json_or_none
from .config import assert_safe_session_id

# Canonical state values
READY = "READY"
QUEUED = "QUEUED"
STARTING = "STARTING"
RUNNING = "RUNNING"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
DONE = "DONE"
BLOCKED = "BLOCKED"
ASSISTANCE_REQUIRED = "ASSISTANCE_REQUIRED"
AUTH_REQUIRED = "AUTH_REQUIRED"
RETRYABLE = "RETRYABLE"
FIX_REQUIRED = "FIX_REQUIRED"
FAILED = "FAILED"

# States eligible for dispatch
CANDIDATE_STATES = {READY, FIX_REQUIRED, RETRYABLE}

# Active states counted against MaxWorkers
ACTIVE_STATES = {QUEUED, STARTING, RUNNING}

# Terminal states
TERMINAL_STATES = {DONE, FAILED, BLOCKED, AUTH_REQUIRED}

ALL_STATES = {
    READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE,
    BLOCKED, ASSISTANCE_REQUIRED, AUTH_REQUIRED, RETRYABLE,
    FIX_REQUIRED, FAILED,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_state(task_dir: str | Path) -> dict[str, Any]:
    """Read state.json from task directory. Returns empty dict if missing."""
    path = Path(task_dir) / "state.json"
    data = read_json_or_none(path)
    if data is None:
        return {}
    return data


def set_state(
    task_dir: str | Path,
    status: str,
    *,
    message: str | None = None,
    exit_code: int | None = None,
    process_id: int | None = None,
    session_id: str | None = None,
    session_mode: str | None = None,
    last_event_at: str | None = None,
    last_heartbeat: str | None = None,
    heartbeat_summary: str | None = None,
    heartbeat_events: int | None = None,
    heartbeat_think: int | None = None,
    heartbeat_tool: int | None = None,
    tokens: Any = None,
) -> dict[str, Any]:
    """Merge-update state.json, preserving existing fields.

    Matches PowerShell Set-State semantics:
    - Reads old state, copies all existing keys
    - Overwrites schemaVersion, taskId, status, updatedAt
    - Only updates optional fields when provided (truthy for strings, non-None for ints)
    """
    path = Path(task_dir) / "state.json"
    old = read_json_or_none(path)

    # Start from old state to preserve all existing fields
    state: dict[str, Any] = {}
    if old:
        state.update(old)

    # Required fields
    state["schemaVersion"] = 1
    state["taskId"] = old.get("taskId", Path(task_dir).name) if old else Path(task_dir).name
    state["status"] = status

    # Attempt: preserve from old or default to 0
    if old and "attempt" in old:
        state["attempt"] = int(old["attempt"])
    elif "attempt" not in state:
        state["attempt"] = 0

    state["updatedAt"] = _now_iso()
    state["message"] = message
    state["processId"] = process_id
    state["exitCode"] = exit_code

    # Optional fields: only set when provided
    if session_id:
        assert_safe_session_id(session_id)
        state["sessionId"] = session_id
    if session_mode:
        state["sessionMode"] = session_mode
    if last_event_at:
        state["lastEventAt"] = last_event_at
    if last_heartbeat:
        state["lastHeartbeat"] = last_heartbeat
    if heartbeat_summary:
        state["heartbeatSummary"] = heartbeat_summary
    if heartbeat_events is not None:
        state["heartbeatEvents"] = heartbeat_events
    if heartbeat_think is not None:
        state["heartbeatThink"] = heartbeat_think
    if heartbeat_tool is not None:
        state["heartbeatTool"] = heartbeat_tool
    if tokens is not None:
        state["tokens"] = tokens

    atomic_write_json(path, state)
    return state


def is_candidate(status: str) -> bool:
    """Check if a status is eligible for dispatch."""
    return status in CANDIDATE_STATES


def is_active(status: str) -> bool:
    """Check if a status counts against MaxWorkers."""
    return status in ACTIVE_STATES


def is_terminal(status: str) -> bool:
    """Check if a status is terminal (no further dispatch)."""
    return status in TERMINAL_STATES