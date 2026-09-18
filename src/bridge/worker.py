# AI生成
"""Worker process management: run a single task via the appropriate transport.

Mirrors PowerShell Invoke-LocalWorker/Invoke-SshWorker dispatch + Complete-WorkerRun.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from .codearts import parse_codearts_json_lines, REQUIRED_MODEL
from .config import ProjectConfig, WorkerConfig
from .state import (
    get_state, set_state, READY, QUEUED, STARTING, RUNNING,
    REVIEW_REQUIRED, DONE, BLOCKED, FAILED, RETRYABLE,
    ASSISTANCE_REQUIRED, AUTH_REQUIRED, FIX_REQUIRED,
)
from .task import get_meta, get_instruction_context, archive_previous_outbox
from .transport import LocalTransport, SshTransport, SshShellTransport, RemoteWorktreeTransport

TRANSPORT_MAP = {
    "local": LocalTransport,
    "ssh": SshTransport,
    "ssh-shell": SshShellTransport,
    "remote-worktree": RemoteWorktreeTransport,
}


def run_worker(
    task_dir: str | Path,
    project: ProjectConfig,
    worker: WorkerConfig | None,
    bridge_root: str | Path,
    quiet: bool = False,
) -> dict:
    """Run a single task through the appropriate transport.

    Returns the final state dict.
    """
    task_dir = Path(task_dir)
    meta = get_meta(task_dir)
    task_id = meta["taskId"]

    # Read current state
    state = get_state(task_dir)
    attempt = int(state.get("attempt", 0)) + 1
    session_id = state.get("sessionId")

    # Archive previous outbox
    archive_previous_outbox(task_dir, attempt)

    # Set STARTING
    set_state(task_dir, STARTING, message=f"attempt {attempt} starting", attempt=attempt)

    # Get transport
    transport_cls = TRANSPORT_MAP.get(project.transport)
    if not transport_cls:
        set_state(task_dir, FAILED, message=f"unsupported transport: {project.transport}")
        return get_state(task_dir)

    transport = transport_cls()

    # Set RUNNING
    set_state(
        task_dir, RUNNING,
        message=f"attempt {attempt} running",
        process_id=__import__("os").getpid(),
    )

    # Calculate timeouts
    timeout_seconds = int(meta.get("hardTimeoutMinutes", 15)) * 60
    soft_timeout_seconds = int(meta.get("softTimeoutMinutes", 12)) * 60
    mode = project.run_mode or "auto"
    baseline = meta.get("baseline")

    # Run
    result = transport.run(
        project=project,
        worker=worker,
        task_dir=task_dir,
        task_id=task_id,
        mode=mode,
        timeout_seconds=timeout_seconds,
        soft_timeout_seconds=soft_timeout_seconds,
        session_id=session_id,
        attempt=attempt,
        baseline=baseline,
        quiet=quiet,
    )

    # Parse telemetry
    telemetry = parse_codearts_json_lines(result.stdout)
    new_session_id = telemetry.get("sessionId") or session_id
    session_mode = "resume" if session_id else "new"

    # Determine final state
    if result.assistance_requested:
        set_state(
            task_dir, ASSISTANCE_REQUIRED,
            message="worker requested assistance",
            exit_code=result.exit_code,
            session_id=new_session_id,
            session_mode=session_mode,
            last_event_at=telemetry.get("lastEventAt"),
            tokens=telemetry.get("tokens"),
        )
    elif result.cancelled:
        set_state(
            task_dir, state.get("status", RUNNING),
            message="cancelled",
            exit_code=result.exit_code,
            session_id=new_session_id,
            session_mode=session_mode,
        )
    elif result.timed_out:
        set_state(
            task_dir, RUNNING,
            message="hard timeout",
            exit_code=result.exit_code,
            session_id=new_session_id,
            session_mode=session_mode,
        )
    elif result.exit_code == 0:
        # Check deliverables
        outbox = task_dir / "outbox"
        has_result = (outbox / "RESULT.md").is_file()
        has_tests = (outbox / "TESTS.md").is_file()
        has_diff = (outbox / "DIFF.stat").is_file()

        if has_result and has_tests and has_diff:
            set_state(
                task_dir, REVIEW_REQUIRED,
                message="deliverables complete",
                exit_code=0,
                session_id=new_session_id,
                session_mode=session_mode,
                last_event_at=telemetry.get("lastEventAt"),
                tokens=telemetry.get("tokens"),
            )
        else:
            set_state(
                task_dir, FAILED,
                message=f"exit 0 but missing deliverables (RESULT={has_result}, TESTS={has_tests}, DIFF={has_diff})",
                exit_code=0,
                session_id=new_session_id,
                session_mode=session_mode,
            )
    else:
        # Non-zero exit
        if result.exit_code in (137, 124):
            status = RUNNING  # timeout kill
        else:
            status = FAILED
        set_state(
            task_dir, status,
            message=f"worker exit code {result.exit_code}",
            exit_code=result.exit_code,
            session_id=new_session_id,
            session_mode=session_mode,
        )

    return get_state(task_dir)