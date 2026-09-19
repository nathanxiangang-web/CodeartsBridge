"""Architect event priority queue with deduplication (AR-01)."""

from __future__ import annotations

import heapq
from dataclasses import dataclass


@dataclass
class ArchitectEvent:
    event_id: str
    type: str
    task_id: str | None
    worker_id: str | None
    priority: int
    created_at: str
    payload: dict
    dedupe_key: str
    attempt: int = 0


def make_dedupe_key(event_type: str, task_id: str | None, attempt: int = 0) -> str:
    """Build a dedupe key in the canonical {type}:{task_id}:{attempt} format."""
    return f"{event_type}:{task_id}:{attempt}"


class ArchitectQueue:
    """Priority queue for Architect events with dedupe by dedupe_key.

    Lower priority numbers are higher priority (P0=0 is highest).
    Pushing an event whose dedupe_key already exists does NOT add a
    duplicate: it upgrades the priority if the new event is higher
    priority and refreshes created_at, then returns False.

    The heap may contain stale entries after a priority upgrade; they
    are skipped lazily during pop/peek by checking that the heap entry
    priority matches the current event priority.
    """

    def __init__(self) -> None:
        self._events: dict[str, ArchitectEvent] = {}
        self._heap: list[tuple[int, int, str]] = []
        self._seq: int = 0

    def push(self, event: ArchitectEvent) -> bool:
        """Add event to queue. Returns True if added, False if deduplicated.

        If an event with the same dedupe_key already exists:
        - Update priority if new event is higher priority (lower number)
        - Update created_at timestamp
        - Do NOT add duplicate
        """
        key = event.dedupe_key
        existing = self._events.get(key)
        if existing is not None:
            if event.priority < existing.priority:
                existing.priority = event.priority
                self._seq += 1
                heapq.heappush(self._heap, (existing.priority, self._seq, key))
            existing.created_at = event.created_at
            return False
        self._events[key] = event
        self._seq += 1
        heapq.heappush(self._heap, (event.priority, self._seq, key))
        return True

    def pop(self) -> ArchitectEvent | None:
        """Pop highest-priority event (lowest priority number = highest priority)."""
        while self._heap:
            priority, _seq, key = heapq.heappop(self._heap)
            existing = self._events.get(key)
            if existing is not None and existing.priority == priority:
                del self._events[key]
                return existing
        return None

    def peek(self) -> ArchitectEvent | None:
        """Peek at the next event without removing it."""
        while self._heap:
            priority, _seq, key = self._heap[0]
            existing = self._events.get(key)
            if existing is not None and existing.priority == priority:
                return existing
            heapq.heappop(self._heap)
        return None

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self._events) == 0

    def size(self) -> int:
        """Number of events in queue."""
        return len(self._events)

    def has_pending(self, task_id: str) -> bool:
        """Check if there are pending events for a task."""
        return any(e.task_id == task_id for e in self._events.values())
