# AI generated
"""Runtime package for CodeartsBridge.

Manages process lifecycle, cancellation, and event echo.

Supervision, heartbeat, session, timeout, and recovery are handled by the
Agent main path (agent/watchdog.py, agent/recovery.py, agent/store.py).
"""

from .process import ManagedProcess, ProcessResult
from .cancellation import (
    request_cancellation, is_cancelled, complete_cancellation,
    get_pending_cancellations,
)

__all__ = [
    "ManagedProcess", "ProcessResult",
    "request_cancellation", "is_cancelled", "complete_cancellation",
    "get_pending_cancellations",
]
