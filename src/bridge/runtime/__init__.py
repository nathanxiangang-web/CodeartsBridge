# AI生成
"""Runtime supervisor package for CodeartsBridge.

Manages task execution lifecycle: process supervision, heartbeat,
cancellation, timeout, session persistence, and stale recovery.
"""

from .process import ManagedProcess, ProcessResult
from .heartbeat import HeartbeatInfo, write_heartbeat, read_heartbeat, is_stale
from .cancellation import (
    request_cancellation, is_cancelled, complete_cancellation,
    get_pending_cancellations,
)
from .timeout import TimeoutConfig, TimeoutStatus, check_timeout, from_task_meta
from .session import Session, create_session, save_session, end_session, find_active_session
from .recovery import recover_stale_sessions, find_stale_sessions, find_orphaned_leases
from .supervisor import Supervisor, SupervisorConfig, ExecutionResult

__all__ = [
    "ManagedProcess", "ProcessResult",
    "HeartbeatInfo", "write_heartbeat", "read_heartbeat", "is_stale",
    "request_cancellation", "is_cancelled", "complete_cancellation",
    "get_pending_cancellations",
    "TimeoutConfig", "TimeoutStatus", "check_timeout", "from_task_meta",
    "Session", "create_session", "save_session", "end_session", "find_active_session",
    "recover_stale_sessions", "find_stale_sessions", "find_orphaned_leases",
    "Supervisor", "SupervisorConfig", "ExecutionResult",
]
