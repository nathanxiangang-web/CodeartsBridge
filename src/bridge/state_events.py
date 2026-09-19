# AI generated
"""Unified state event emission.

Provides a single emit_state_changed() function called by both
src/bridge/state.py and src/bridge/core/state.py whenever task state
changes. Bumps state revision and maps state transitions to event
types, appending events to the EventStore.

All event emission is best-effort: if the EventStore write fails,
the state change itself still succeeds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _map_event_type(old_state: str | None, new_state: str) -> str:
    """Map a (old_state, new_state) transition to an event type.

    Falls back to the generic task.state_changed event type for
    transitions without a specific mapping.
    """
    if old_state == "RUNNING" and new_state == "REVIEW_REQUIRED":
        return "review.required"
    if old_state == "RUNNING" and new_state == "ASSISTANCE_REQUIRED":
        return "assistance.required"
    if old_state == "RUNNING" and new_state == "FAILED":
        return "task.failed"
    if old_state == "REVIEW_REQUIRED" and new_state == "APPROVED":
        return "review.completed"
    if new_state in ("FIX_REQUIRED", "READY"):
        return "task.dispatchable"
    if new_state == "DONE":
        return "task.done"
    return "task.state_changed"


def emit_state_changed(
    bridge_root: Path,
    task_dir: Path,
    old_state: str,
    new_state: str,
    state: dict,
) -> None:
    """Emit a task.state_changed event to the EventStore.

    Also bumps state revision and maps state transitions to event types.
    Best-effort: if EventStore write fails, state change still succeeds.
    """
    bridge_root = Path(bridge_root)
    task_dir = Path(task_dir)

    # Revision is already bumped by the caller (state.py / core/state.py).
    # Ensure it exists for the event payload; default to 0 if missing.
    revision = state.get("revision", 0)
    if not isinstance(revision, int):
        revision = 0

    # Emit event to EventStore. Best-effort: failures must not roll
    # back the state change or the revision bump above.
    try:
        from .core.events import Event, EventStore

        event_type = _map_event_type(old_state, new_state)
        task_id = state.get("taskId", task_dir.name)

        store = EventStore(bridge_root / "events")
        event = Event(
            event_id="",
            type=event_type,
            task_id=task_id,
            payload={
                "oldState": old_state,
                "newState": new_state,
                "revision": revision,
            },
        )
        store.append(event)
    except Exception:
        pass
