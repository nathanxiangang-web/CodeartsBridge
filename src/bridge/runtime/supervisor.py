# AI生成
"""Runtime supervisor — orchestrates task execution lifecycle.

The supervisor manages:
- Starting tasks via agent adapters
- Heartbeat monitoring
- Soft/hard timeout enforcement
- Graceful cancellation (SIGTERM → grace → SIGKILL)
- Session persistence and recovery
- Lease renewal during execution
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..atomic import read_json_or_none, atomic_write_json
from ..core.state import (
    get_state, set_state,
    QUEUED, STARTING, RUNNING, REVIEW_REQUIRED,
    BLOCKED, FAILED, RETRYABLE, STALE,
)
from .process import ManagedProcess, ProcessResult
from .heartbeat import HeartbeatInfo, write_heartbeat, read_heartbeat, remove_heartbeat
from .cancellation import (
    is_cancelled, get_cancellation, complete_cancellation,
    get_pending_cancellations,
)
from .timeout import TimeoutConfig, TimeoutStatus, check_timeout, from_task_meta
from .session import Session, create_session, save_session, end_session, find_active_session
from .recovery import recover_stale_sessions, find_orphaned_leases

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


@dataclass
class SupervisorConfig:
    grace_period_seconds: float = 10.0
    stale_heartbeat_minutes: int = 5
    heartbeat_interval_seconds: float = 30.0
    poll_interval_seconds: float = 2.0
    max_attempts: int = 3


@dataclass
class ExecutionResult:
    task_id: str
    session_id: str
    success: bool
    exit_code: int
    timed_out: bool = False
    cancelled: bool = False
    duration_seconds: float = 0.0
    error: str = ""


class Supervisor:
    """Runtime supervisor for managing task execution."""

    def __init__(
        self,
        bridge_root: Path,
        runtime_dir: Path | None = None,
        config: SupervisorConfig | None = None,
    ):
        self.bridge_root = Path(bridge_root)
        self.runtime_dir = runtime_dir or (self.bridge_root / "runtime")
        self.config = config or SupervisorConfig()
        self._processes: dict[str, ManagedProcess] = {}
        self._sessions: dict[str, Session] = {}
        self._start_times: dict[str, datetime] = {}

    def start_task(
        self,
        task_id: str,
        worker_id: str,
        assignment_id: str,
        command: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout_config: TimeoutConfig | None = None,
        attempt: int = 1,
    ) -> Session:
        """Start a task execution under supervision."""
        # Check for cancellation before starting
        if is_cancelled(self.runtime_dir, task_id):
            logger.info("Task %s cancelled before start", task_id)
            raise RuntimeError(f"Task {task_id} has pending cancellation")

        # Transition state: QUEUED → STARTING
        task_dir = self.bridge_root / "tasks" / task_id
        current = get_state(task_dir).get("state", "CREATED")
        if current not in (QUEUED, RETRYABLE):
            raise RuntimeError(
                f"Task {task_id} cannot start from state {current}"
            )

        set_state(task_dir, STARTING)

        # Create session
        session = create_session(
            self.runtime_dir, task_id, worker_id, assignment_id, attempt
        )

        # Set up log paths
        log_dir = self.runtime_dir / "logs" / task_id
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_file = log_dir / f"attempt-{attempt}.stdout.log"
        stderr_file = log_dir / f"attempt-{attempt}.stderr.log"
        session.log_path = str(log_dir)

        # Start process
        proc = ManagedProcess(
            command=command,
            cwd=cwd,
            env=env,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
        )
        proc.start()

        session.pid = proc.pid
        save_session(self.runtime_dir, session)

        # Transition state: STARTING → RUNNING
        set_state(task_dir, RUNNING)

        self._processes[task_id] = proc
        self._sessions[task_id] = session
        self._start_times[task_id] = _now()

        # Write initial heartbeat
        hb = HeartbeatInfo(task_id=task_id, worker_id=worker_id)
        write_heartbeat(self.runtime_dir, hb)

        logger.info(
            "Started task %s on worker %s (pid=%s, session=%s)",
            task_id, worker_id, proc.pid, session.session_id,
        )
        return session

    def monitor_task(
        self,
        task_id: str,
        timeout_config: TimeoutConfig | None = None,
        on_heartbeat: Callable | None = None,
    ) -> ExecutionResult:
        """Monitor a running task until completion, timeout, or cancellation.

        This is a blocking call. For non-blocking use, poll with check_task().
        """
        proc = self._processes.get(task_id)
        session = self._sessions.get(task_id)
        if proc is None or session is None:
            raise RuntimeError(f"Task {task_id} is not being supervised")

        start_time = self._start_times[task_id]
        start_perf = time.monotonic()

        while True:
            # Check if process finished
            if not proc.is_running:
                exit_code = proc.wait()
                duration = time.monotonic() - start_perf
                return self._finish_task(
                    task_id, exit_code, duration, session
                )

            # Check cancellation
            if is_cancelled(self.runtime_dir, task_id):
                logger.info("Cancelling task %s", task_id)
                exit_code = proc.terminate_graceful(
                    grace_seconds=self.config.grace_period_seconds
                )
                duration = time.monotonic() - start_perf
                complete_cancellation(self.runtime_dir, task_id, exit_code)
                self._cleanup_task(task_id)
                end_session(self.runtime_dir, session.session_id, "cancelled", exit_code)
                return ExecutionResult(
                    task_id=task_id,
                    session_id=session.session_id,
                    success=False,
                    exit_code=exit_code,
                    cancelled=True,
                    duration_seconds=duration,
                )

            # Check timeout
            if timeout_config:
                status = check_timeout(start_time, timeout_config)
                if status.hard_exceeded:
                    logger.warning(
                        "Hard timeout for task %s (%.1f min)",
                        task_id, status.elapsed_minutes,
                    )
                    exit_code = proc.kill()
                    duration = time.monotonic() - start_perf
                    self._cleanup_task(task_id)
                    end_session(self.runtime_dir, session.session_id, "timed_out", exit_code)
                    task_dir = self.bridge_root / "tasks" / task_id
                    set_state(task_dir, FAILED)
                    return ExecutionResult(
                        task_id=task_id,
                        session_id=session.session_id,
                        success=False,
                        exit_code=exit_code,
                        timed_out=True,
                        duration_seconds=duration,
                        error=f"Hard timeout at {status.elapsed_minutes:.1f} min",
                    )

                if status.soft_exceeded:
                    logger.info(
                        "Soft timeout warning for task %s (%.1f min)",
                        task_id, status.elapsed_minutes,
                    )

            # Write heartbeat
            elapsed = time.monotonic() - start_perf
            hb = HeartbeatInfo(
                task_id=task_id,
                worker_id=session.worker_id,
                elapsed_seconds=elapsed,
            )
            write_heartbeat(self.runtime_dir, hb)
            if on_heartbeat:
                on_heartbeat(hb)

            # Wait before next poll
            time.sleep(self.config.poll_interval_seconds)

    def _finish_task(
        self,
        task_id: str,
        exit_code: int,
        duration: float,
        session: Session,
    ) -> ExecutionResult:
        """Handle task completion."""
        self._cleanup_task(task_id)

        success = exit_code == 0
        status = "completed" if success else "failed"
        end_session(self.runtime_dir, session.session_id, status, exit_code)

        task_dir = self.bridge_root / "tasks" / task_id
        if success:
            set_state(task_dir, REVIEW_REQUIRED)
        else:
            set_state(task_dir, FAILED)

        return ExecutionResult(
            task_id=task_id,
            session_id=session.session_id,
            success=success,
            exit_code=exit_code,
            duration_seconds=duration,
        )

    def _cleanup_task(self, task_id: str) -> None:
        """Clean up in-memory tracking for a task."""
        self._processes.pop(task_id, None)
        self._sessions.pop(task_id, None)
        self._start_times.pop(task_id, None)
        remove_heartbeat(self.runtime_dir, task_id)

    def cancel_task(self, task_id: str, reason: str = "") -> None:
        """Request cancellation of a running task."""
        from .cancellation import request_cancellation
        request_cancellation(self.runtime_dir, task_id, reason)

    def check_task(self, task_id: str) -> dict:
        """Non-blocking status check for a supervised task."""
        proc = self._processes.get(task_id)
        session = self._sessions.get(task_id)
        hb = read_heartbeat(self.runtime_dir, task_id)

        return {
            "taskId": task_id,
            "running": proc.is_running if proc else False,
            "pid": proc.pid if proc else None,
            "sessionId": session.session_id if session else None,
            "elapsed": proc.elapsed if proc else 0.0,
            "heartbeat": hb.to_dict() if hb else None,
            "cancelled": is_cancelled(self.runtime_dir, task_id),
        }

    def recover(self) -> list[str]:
        """Recover stale sessions and orphaned leases after bridge restart."""
        recovered = recover_stale_sessions(
            self.runtime_dir, self.config.stale_heartbeat_minutes
        )
        for task_id in recovered:
            task_dir = self.bridge_root / "tasks" / task_id
            set_state(task_dir, STALE)
            logger.warning("Recovered stale session for task %s", task_id)
        return recovered

    def process_pending_cancellations(self) -> list[str]:
        """Process any pending cancellation requests for supervised tasks."""
        pending = get_pending_cancellations(self.runtime_dir)
        cancelled = []
        for task_id in pending:
            proc = self._processes.get(task_id)
            if proc and proc.is_running:
                exit_code = proc.terminate_graceful(
                    grace_seconds=self.config.grace_period_seconds
                )
                complete_cancellation(self.runtime_dir, task_id, exit_code)
                self._cleanup_task(task_id)
                cancelled.append(task_id)
        return cancelled
