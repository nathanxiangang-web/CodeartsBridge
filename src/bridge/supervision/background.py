"""Background scheduler for architect idle-time tasks (AR-04).

Allows the Architect to run short background tasks during slack time
between supervision deadlines.  Tasks are bounded by max_seconds and
only start when there is sufficient slack before the next deadline.
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class BackgroundScheduler:
    """Run short background tasks during architect idle time.

    Args:
        max_seconds: Maximum wall-clock seconds a background task may run.
        reserve_seconds: Seconds to reserve before the next deadline.
        min_slack: Minimum slack required to start a background task.
    """

    def __init__(
        self,
        max_seconds: int = 90,
        reserve_seconds: int = 30,
        min_slack: int = 120,
    ) -> None:
        self._max_seconds = max_seconds
        self._reserve_seconds = reserve_seconds
        self._min_slack = min_slack
        self._thread: threading.Thread | None = None
        self._deadline: float = 0.0

    def try_run(self, task_fn: Callable[[], None], slack_seconds: float) -> bool:
        """Attempt to run a background task if slack is sufficient.

        Returns True if the task was started, False if skipped due to
        insufficient slack.
        """
        if slack_seconds <= self._min_slack:
            return False
        if self._thread is not None and self._thread.is_alive():
            return False

        budget = min(self._max_seconds, slack_seconds - self._reserve_seconds)
        if budget <= 0:
            return False

        self._deadline = time.monotonic() + budget

        def _runner() -> None:
            try:
                task_fn()
            except Exception:
                pass

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()
        return True

    def is_running(self) -> bool:
        """Check if a background task is currently running."""
        return self._thread is not None and self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the current background task to finish."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)