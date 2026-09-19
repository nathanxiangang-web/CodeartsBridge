from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Protocol

from bridge.core.events import Event
from bridge.state import (
    ASSISTANCE_REQUIRED,
    REVIEW_REQUIRED,
    TERMINAL_STATES,
    get_state,
)

logger = logging.getLogger(__name__)

ASSISTANCE_REQUIRED_EVENT = "assistance.required"
SUPERVISION_ALERT = "supervision.alert"
CAPACITY_AVAILABLE = "capacity.available"
DEPENDENCY_UNLOCKED = "dependency.unlocked"

_EVENT_EXPECTED_STATE: dict[str, str | None] = {
    "review.required": REVIEW_REQUIRED,
    ASSISTANCE_REQUIRED_EVENT: ASSISTANCE_REQUIRED,
    SUPERVISION_ALERT: None,
    "runtime.timeout": None,
    CAPACITY_AVAILABLE: None,
    DEPENDENCY_UNLOCKED: None,
}

_ALERT_CONTEXT_FIELDS = (
    "task_id",
    "worker_id",
    "elapsed",
    "last_progress",
    "repeated_errors",
    "diff_state",
    "outbox_state",
)


class ArchitectQueue(Protocol):
    def pop(self) -> Event | None:
        ...

    def is_empty(self) -> bool:
        ...


class ArchitectReactor:
    def __init__(
        self,
        queue: ArchitectQueue,
        bridge_root: Path,
        *,
        review_task_fn: Callable[[str, Path], Any] | None = None,
        assistance_analyzer: Callable[[Event, Path], str] | None = None,
        salvage_handler: Callable[[Event, Path], Any] | None = None,
        capacity_handler: Callable[[Event, Path], Any] | None = None,
        dependency_handler: Callable[[Event, Path], Any] | None = None,
    ) -> None:
        self._queue = queue
        self._bridge_root = Path(bridge_root)
        self._review_task_fn = review_task_fn
        self._assistance_analyzer = assistance_analyzer
        self._salvage_handler = salvage_handler
        self._capacity_handler = capacity_handler
        self._dependency_handler = dependency_handler
        self._review_lock: set[str] = set()
        self.actions: list[dict[str, Any]] = []
        self.last_alert_context: dict[str, Any] | None = None
        self.last_assistance_decision: str | None = None

    def process_next(self) -> bool:
        event = self._queue.pop()
        if event is None:
            return False
        self._dispatch(event)
        return True

    def process_batch(self, max_events: int = 10) -> int:
        count = 0
        while count < max_events:
            if not self.process_next():
                break
            count += 1
        return count

    def is_idle(self) -> bool:
        return self._queue.is_empty()

    def _acquire_review_lock(self, task_id: str) -> bool:
        if task_id in self._review_lock:
            return False
        self._review_lock.add(task_id)
        return True

    def _release_review_lock(self, task_id: str) -> None:
        self._review_lock.discard(task_id)

    def _dispatch(self, event: Event) -> None:
        et = event.type
        if et == "review.required":
            self._handle_review_required(event)
        elif et == ASSISTANCE_REQUIRED_EVENT:
            self._handle_assistance_required(event)
        elif et == SUPERVISION_ALERT:
            self._handle_supervision_alert(event)
        elif et == "runtime.timeout":
            self._handle_runtime_timeout(event)
        elif et == CAPACITY_AVAILABLE:
            self._handle_capacity_available(event)
        elif et == DEPENDENCY_UNLOCKED:
            self._handle_dependency_unlocked(event)
        else:
            logger.warning("No handler for event type: %s", et)
            self.actions.append({"action": "unknown", "event_type": et})

    def _state_matches(self, event_type: str, task_id: str | None) -> bool:
        expected = _EVENT_EXPECTED_STATE.get(event_type)
        if expected is None:
            return True
        if task_id is None:
            return False
        task_dir = self._bridge_root / "tasks" / task_id
        current = get_state(task_dir).get("state", "")
        return current == expected

    def _handle_review_required(self, event: Event) -> None:
        task_id = event.task_id
        if task_id is None:
            return
        if not self._state_matches(event.type, task_id):
            self.actions.append(
                {"action": "skip", "reason": "state_mismatch", "task_id": task_id}
            )
            return
        if not self._acquire_review_lock(task_id):
            self.actions.append(
                {"action": "skip", "reason": "review_locked", "task_id": task_id}
            )
            return
        try:
            fn = self._review_task_fn or self._default_review_task
            verdict = fn(task_id, self._bridge_root)
            self.actions.append(
                {"action": "review", "task_id": task_id, "verdict": verdict}
            )
        finally:
            self._release_review_lock(task_id)

    def _default_review_task(self, task_id: str, bridge_root: Path) -> Any:
        from bridge.architect_loop import review_task

        return review_task(task_id, bridge_root)

    def _handle_assistance_required(self, event: Event) -> None:
        task_id = event.task_id
        if task_id is None:
            return
        if not self._state_matches(event.type, task_id):
            self.actions.append(
                {"action": "skip", "reason": "state_mismatch", "task_id": task_id}
            )
            return
        analyzer = self._assistance_analyzer or self._default_assistance_analyzer
        decision = analyzer(event, self._bridge_root)
        self.last_assistance_decision = decision
        self.actions.append(
            {"action": "assistance", "task_id": task_id, "decision": decision}
        )

    def _default_assistance_analyzer(self, event: Event, bridge_root: Path) -> str:
        return "escalate"

    def _handle_supervision_alert(self, event: Event) -> None:
        ctx = self._prepare_alert_context(event)
        self.last_alert_context = ctx
        logger.warning("supervision.alert for task %s: %s", event.task_id, ctx)
        self.actions.append(
            {"action": "alert", "task_id": event.task_id, "context": ctx}
        )

    def _prepare_alert_context(self, event: Event) -> dict[str, Any]:
        payload = event.payload or {}
        task_id = event.task_id
        state: dict[str, Any] = {}
        if task_id is not None:
            task_dir = self._bridge_root / "tasks" / task_id
            state = get_state(task_dir)
        return {
            "task_id": task_id,
            "worker_id": event.worker_id or state.get("assignedWorkerId"),
            "elapsed": payload.get("elapsed"),
            "last_progress": payload.get("last_progress")
            or state.get("lastHeartbeat"),
            "repeated_errors": payload.get("repeated_errors")
            or state.get("repeatedErrorCount"),
            "diff_state": payload.get("diff_state"),
            "outbox_state": payload.get("outbox_state"),
        }

    def _handle_runtime_timeout(self, event: Event) -> None:
        task_id = event.task_id
        logger.warning("runtime.timeout for task %s", task_id)
        if task_id is not None:
            task_dir = self._bridge_root / "tasks" / task_id
            current = get_state(task_dir).get("state", "")
            if current in TERMINAL_STATES:
                self.actions.append(
                    {
                        "action": "timeout_skip",
                        "task_id": task_id,
                        "reason": "terminal",
                    }
                )
                return
        handler = self._salvage_handler or self._default_salvage
        result = handler(event, self._bridge_root)
        self.actions.append(
            {"action": "timeout_salvage", "task_id": task_id, "result": result}
        )

    def _default_salvage(self, event: Event, bridge_root: Path) -> Any:
        return None

    def _handle_capacity_available(self, event: Event) -> None:
        handler = self._capacity_handler or self._default_capacity
        result = handler(event, self._bridge_root)
        self.actions.append({"action": "capacity", "result": result})

    def _default_capacity(self, event: Event, bridge_root: Path) -> Any:
        return None

    def _handle_dependency_unlocked(self, event: Event) -> None:
        task_id = event.task_id
        handler = self._dependency_handler or self._default_dependency
        result = handler(event, self._bridge_root)
        self.actions.append(
            {"action": "dependency_unlocked", "task_id": task_id, "result": result}
        )

    def _default_dependency(self, event: Event, bridge_root: Path) -> Any:
        return None
