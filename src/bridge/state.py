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
CREATED = "CREATED"
QUEUED = "QUEUED"
STARTING = "STARTING"
RUNNING = "RUNNING"
VERIFYING = "VERIFYING"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
APPROVED = "APPROVED"
DONE = "DONE"
BLOCKED = "BLOCKED"
ASSISTANCE_REQUIRED = "ASSISTANCE_REQUIRED"
AUTH_REQUIRED = "AUTH_REQUIRED"
RETRYABLE = "RETRYABLE"
FIX_REQUIRED = "FIX_REQUIRED"
FAILED = "FAILED"
CANCEL_REQUESTED = "CANCEL_REQUESTED"
CANCELLED = "CANCELLED"
INTEGRATION_FAILED = "INTEGRATION_FAILED"

# States eligible for dispatch
CANDIDATE_STATES = {READY, FIX_REQUIRED, RETRYABLE}

# Active worker-execution states counted against MaxWorkers
ACTIVE_STATES = {QUEUED, STARTING, RUNNING, VERIFYING}

# Terminal states
TERMINAL_STATES = {DONE, FAILED, BLOCKED, AUTH_REQUIRED, CANCELLED, INTEGRATION_FAILED}

ALL_STATES = {
    READY, CREATED, QUEUED, STARTING, RUNNING, VERIFYING, REVIEW_REQUIRED, APPROVED, DONE,
    BLOCKED, ASSISTANCE_REQUIRED, AUTH_REQUIRED, RETRYABLE,
    FIX_REQUIRED, FAILED, CANCEL_REQUESTED, CANCELLED, INTEGRATION_FAILED,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_STATE_TIMESTAMPS: dict[str, str] = {
    QUEUED: "queuedAt",
    STARTING: "startedAt",
    RUNNING: "runningAt",
    VERIFYING: "finishedAt",
    REVIEW_REQUIRED: "reviewReadyAt",
    DONE: "doneAt",
    FIX_REQUIRED: "reviewedAt",
    CANCELLED: "cancelledAt",
    FAILED: "failedAt",
    BLOCKED: "blockedAt",
    ASSISTANCE_REQUIRED: "assistanceAt",
    AUTH_REQUIRED: "authAt",
    RETRYABLE: "retryableAt",
}


def get_state(task_dir: str | Path) -> dict[str, Any]:
    """Read state.json and normalize legacy/v2 state aliases.

    Both runtime layers share the same state.json. Historically the v2 layer
    updated only state while legacy consumers preferred status, which could
    leave a task apparently stuck in an older state. Treat state as canonical
    when both exist and mirror it to status.
    """
    path = Path(task_dir) / "state.json"
    data = read_json_or_none(path)
    if data is None:
        return {}

    state_value = data.get("state")
    status_value = data.get("status")
    if state_value:
        data["status"] = state_value
    elif status_value:
        data["state"] = status_value
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
    attempt: int | None = None,
    assigned_worker_id: str | None = None,
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
    state["state"] = status

    # Attempt: preserve from old or default to 0, or use provided value
    if attempt is not None:
        state["attempt"] = attempt
    elif old and "attempt" in old:
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
    if assigned_worker_id is not None:
        state["assignedWorkerId"] = assigned_worker_id

    # Auto-record timestamp for state transitions
    ts_field = _STATE_TIMESTAMPS.get(status)
    if ts_field and ts_field not in state:
        state[ts_field] = _now_iso()

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