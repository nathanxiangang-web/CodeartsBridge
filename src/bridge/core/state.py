# AI生成
"""Task state machine v2.

States:
    CREATED → READY → QUEUED → STARTING → RUNNING
    RUNNING → {ASSISTANCE_REQUIRED, RETRYABLE, AUTH_REQUIRED, CANCELLED, FAILED, STALE}
    RUNNING → VERIFYING → {FIX_REQUIRED, FAILED}
    VERIFYING → REVIEW_REQUIRED → {FIX_REQUIRED → QUEUED, APPROVED}
    APPROVED → INTEGRATING → {CONFLICT, FAILED}
    INTEGRATING → INTEGRATED → DONE
"""

from __future__ import annotations

import json
from pathlib import Path

# --- Primary states ---
CREATED = "CREATED"
READY = "READY"
QUEUED = "QUEUED"
STARTING = "STARTING"
RUNNING = "RUNNING"
VERIFYING = "VERIFYING"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
APPROVED = "APPROVED"
INTEGRATING = "INTEGRATING"
INTEGRATED = "INTEGRATED"
DONE = "DONE"

# --- Branch states ---
ASSISTANCE_REQUIRED = "ASSISTANCE_REQUIRED"
RETRYABLE = "RETRYABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
CANCELLED = "CANCELLED"
FAILED = "FAILED"
FIX_REQUIRED = "FIX_REQUIRED"
CONFLICT = "CONFLICT"
STALE = "STALE"
BLOCKED = "BLOCKED"
INTEGRATION_FAILED = "INTEGRATION_FAILED"

# --- State sets ---
CANDIDATE_STATES = {READY, FIX_REQUIRED, RETRYABLE}
ACTIVE_STATES = {QUEUED, STARTING, RUNNING, VERIFYING, REVIEW_REQUIRED, APPROVED, INTEGRATING, INTEGRATED}
TERMINAL_STATES = {DONE, FAILED, CANCELLED, BLOCKED, AUTH_REQUIRED, INTEGRATION_FAILED}
REVIEWABLE_STATES = {REVIEW_REQUIRED}
INTEGRABLE_STATES = {APPROVED}

ALL_STATES = CANDIDATE_STATES | ACTIVE_STATES | TERMINAL_STATES | {CREATED, ASSISTANCE_REQUIRED, CONFLICT, STALE}

# --- Valid transitions ---
_TRANSITIONS: dict[str, set[str]] = {
    CREATED: {READY},
    READY: {QUEUED, CANCELLED},
    QUEUED: {STARTING, CANCELLED, BLOCKED},
    STARTING: {RUNNING, FAILED, AUTH_REQUIRED, CANCELLED},
    RUNNING: {
        VERIFYING, ASSISTANCE_REQUIRED, RETRYABLE, AUTH_REQUIRED,
        CANCELLED, FAILED, STALE,
    },
    STALE: {RUNNING, RETRYABLE, FAILED, CANCELLED},
    VERIFYING: {REVIEW_REQUIRED, FIX_REQUIRED, FAILED},
    REVIEW_REQUIRED: {FIX_REQUIRED, APPROVED, CANCELLED},
    FIX_REQUIRED: {QUEUED, CANCELLED},
    APPROVED: {INTEGRATING, CANCELLED},
    INTEGRATING: {INTEGRATED, CONFLICT, FAILED, CANCELLED, INTEGRATION_FAILED},
    CONFLICT: {INTEGRATING, FIX_REQUIRED, FAILED, CANCELLED},
    INTEGRATED: {DONE, FAILED},
    RETRYABLE: {QUEUED, CANCELLED, FAILED},
    ASSISTANCE_REQUIRED: {RUNNING, CANCELLED, FAILED},
    AUTH_REQUIRED: {QUEUED, CANCELLED, FAILED},
    # Terminal states have no outgoing transitions
    DONE: set(),
    FAILED: set(),
    CANCELLED: set(),
    BLOCKED: set(),
    INTEGRATION_FAILED: set(),
}


def is_valid_transition(from_state: str, to_state: str) -> bool:
    return to_state in _TRANSITIONS.get(from_state, set())


def is_candidate(state: str) -> bool:
    return state in CANDIDATE_STATES


def is_active(state: str) -> bool:
    return state in ACTIVE_STATES


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def get_state(task_dir: Path) -> dict:
    """Read state.json and normalize the shared legacy/v2 aliases."""
    state_file = Path(task_dir) / "state.json"
    if not state_file.exists():
        return {"state": CREATED, "status": CREATED}

    data = json.loads(state_file.read_text(encoding="utf-8"))
    state_value = data.get("state")
    status_value = data.get("status")
    if state_value:
        data["status"] = state_value
    elif status_value:
        data["state"] = status_value
    else:
        data["state"] = CREATED
        data["status"] = CREATED
    return data


def set_state(task_dir: Path, state: str, **extra) -> dict:
    """Atomically update state.json with a new state and extra fields."""
    from ..atomic import atomic_write_json, read_json_or_none

    task_dir = Path(task_dir)
    current = read_json_or_none(task_dir / "state.json") or {}
    from_state = current.get("state") or current.get("status") or CREATED

    if from_state != state and not is_valid_transition(from_state, state):
        from ..core.errors import StateTransitionError
        raise StateTransitionError(from_state, state)

    # state.json is shared with the legacy runtime. Keep both aliases in
    # lockstep so legacy readers never observe a stale transition.
    current["state"] = state
    current["status"] = state
    current.update(extra)
    # Extra payloads must not be able to re-introduce alias divergence.
    current["state"] = state
    current["status"] = state
    # Revision: monotonically increasing on each state change (ST-01)
    current["revision"] = int(current.get("revision", 0)) + 1
    atomic_write_json(task_dir / "state.json", current)

    # Emit unified state event (best-effort). bridge_root is inferred
    # from the standard layout <bridge_root>/tasks/<task_id>.
    try:
        from ..state_events import emit_state_changed
        bridge_root = task_dir.parent.parent
        emit_state_changed(bridge_root, task_dir, from_state, state, current)
    except Exception:
        pass

    return current
