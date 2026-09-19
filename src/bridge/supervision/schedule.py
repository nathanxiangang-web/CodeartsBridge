"""Per-task deadline scheduler using a heap with generation tokens."""

from __future__ import annotations

import heapq
from datetime import datetime, timedelta
from typing import Iterator

from bridge.supervision.model import (
    SUPERVISION_OFFSETS_SECONDS,
    DeadlineEntry,
)


def _compute_due_wallclock(running_at_wallclock: str, offset_seconds: int) -> str:
    wc = running_at_wallclock
    if wc.endswith("Z"):
        wc = wc[:-1] + "+00:00"
    dt = datetime.fromisoformat(wc)
    return (dt + timedelta(seconds=offset_seconds)).isoformat()


class DeadlineScheduler:
    """Schedule per-task inspection deadlines on a shared heap.

    Cancellation is O(1): each task_id has a generation counter stored in
    _generation.  Cancelling increments the counter so existing heap
    entries (which carry the old generation) are skipped lazily when popped.
    A new start_task for an already-tracked task_id also bumps the
    generation, invalidating any prior deadlines for that task.
    """

    def __init__(self) -> None:
        self._heap: list[DeadlineEntry] = []
        self._generation: dict[str, int] = {}

    def start_task(
        self,
        task_id: str,
        running_at_monotonic: float,
        running_at_wallclock: str,
    ) -> None:
        """Schedule all 6 inspection deadlines for a task.

        If the task_id was previously scheduled, the old deadlines are
        invalidated by bumping the generation token before pushing the new
        entries.
        """
        gen = self._generation.get(task_id, -1) + 1
        self._generation[task_id] = gen
        for stage, offset in enumerate(SUPERVISION_OFFSETS_SECONDS):
            entry = DeadlineEntry(
                due_monotonic=running_at_monotonic + offset,
                due_wallclock=_compute_due_wallclock(running_at_wallclock, offset),
                task_id=task_id,
                stage=stage,
                generation=gen,
            )
            heapq.heappush(self._heap, entry)

    def cancel_task(self, task_id: str) -> None:
        """Cancel all future deadlines for a task by bumping its generation.

        Existing heap entries are left in place (O(1)); they are skipped
        lazily by pop_due / next_due_at because their generation no
        longer matches the current token.
        """
        if task_id in self._generation:
            self._generation[task_id] += 1

    def pop_due(self, now_monotonic: float) -> Iterator[DeadlineEntry]:
        """Yield all entries that are due, skipping cancelled generations.

        Due entries (due_monotonic <= now_monotonic) are removed from the
        heap.  Entries whose generation no longer matches the current token
        for their task_id are discarded silently.
        """
        while self._heap:
            top = self._heap[0]
            if top.due_monotonic > now_monotonic:
                break
            heapq.heappop(self._heap)
            current_gen = self._generation.get(top.task_id)
            if current_gen is not None and top.generation == current_gen:
                yield top

    def next_due_at(self) -> float | None:
        """Return the monotonic time of the next valid deadline, or None.

        Scans the heap for the earliest entry whose generation still matches
        the current token for its task_id.  Does not modify the heap.
        """
        best: float | None = None
        for entry in self._heap:
            current_gen = self._generation.get(entry.task_id)
            if current_gen is None or entry.generation != current_gen:
                continue
            if best is None or entry.due_monotonic < best:
                best = entry.due_monotonic
        return best
