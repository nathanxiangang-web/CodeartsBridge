"""Capacity event monitor for idle-worker detection (AR-05).

Fires a capacity.available architect event when enabled workers are
idle (running < enabled) and there is no ready work but pending work
exists.  Includes a per-project cooldown to prevent spam.
"""

from __future__ import annotations

import time

from bridge.supervision.model import ArchitectEvent


class CapacityMonitor:
    """Detect idle capacity and emit capacity.available events.

    Args:
        cooldown_seconds: Per-project cooldown between capacity events.
    """

    def __init__(self, cooldown_seconds: int = 60) -> None:
        self._cooldown = cooldown_seconds
        self._last_fired: dict[str, float] = {}

    def can_fire(self, project_id: str) -> bool:
        """Check if cooldown has elapsed for the given project."""
        now = time.monotonic()
        last = self._last_fired.get(project_id, 0.0)
        return (now - last) >= self._cooldown

    def check(
        self,
        enabled_workers: int,
        running_workers: int,
        ready_tasks: int,
        has_pending_work: bool,
        project_id: str = "default",
    ) -> ArchitectEvent | None:
        """Check for idle capacity and return an event if conditions are met.

        Fires when:
        - enabled_workers > running_workers (idle workers exist)
        - ready_tasks == 0 (no ready work to assign)
        - has_pending_work (there is known future work)
        - cooldown has elapsed for this project
        """
        if not self.can_fire(project_id):
            return None
        if enabled_workers <= running_workers:
            return None
        if ready_tasks > 0:
            return None
        if not has_pending_work:
            return None

        self._last_fired[project_id] = time.monotonic()
        return ArchitectEvent(
            task_id="",
            event_type="capacity.available",
            stage=0,
            summary=f"{enabled_workers - running_workers} idle workers, pending work exists",
            payload={
                "enabledWorkers": enabled_workers,
                "runningWorkers": running_workers,
                "readyTasks": ready_tasks,
                "projectId": project_id,
            },
        )