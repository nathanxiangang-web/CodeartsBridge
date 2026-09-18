# AI生成
"""Worker process management: run a single task via the appropriate transport.

Mirrors PowerShell Invoke-LocalWorker/Invoke-SshWorker dispatch + Complete-WorkerRun.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from .codearts import parse_codearts_json_lines, REQUIRED_MODEL, resolve_model
from .config import ProjectConfig, WorkerConfig
from .state import (
    get_state, set_state, READY, QUEUED, STARTING, RUNNING,
    REVIEW_REQUIRED, DONE, BLOCKED, FAILED, RETRYABLE,
    ASSISTANCE_REQUIRED, AUTH_REQUIRED, FIX_REQUIRED,
)
from .task import get_meta, get_instruction_context, archive_previous_outbox
from .transport import LocalTransport, SshTransport, SshShellTransport, RemoteWorktreeTransport
from .policy.integration import (
    load_profile_for_project,
    evaluate_pre_checks,
    evaluate_task_policy,
    should_block_task,
    should_transition_to_review,
)

TRANSPORT_MAP = {
    "local": LocalTransport,
    "ssh": SshTransport,
    "ssh-shell": SshShellTransport,
    "remote-worktree": RemoteWorktreeTransport,
}


def _run_worker_inner(
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

    # Calculate timeouts from META v2 execution config.
    # Top-level fields remain a compatibility fallback for legacy tasks.
    execution = meta.get("execution") or {}
    timeout_seconds = int(
        execution.get("hardTimeoutMinutes", meta.get("hardTimeoutMinutes", 15))
    ) * 60
    soft_timeout_seconds = int(
        execution.get("softTimeoutMinutes", meta.get("softTimeoutMinutes", 12))
    ) * 60
    mode = project.run_mode or "auto"
    baseline = meta.get("baseline")
    role = meta.get("role", "implement")
    resolved_model = resolve_model(role=role, worker=worker, project=project)

    # Load policy profile (optional)
    policy_profile = load_profile_for_project(
        Path(bridge_root), project.id
    )

    # PreChecks: run before worker execution
    if policy_profile is not None:
        pre_result = evaluate_pre_checks(
            policy_profile, task_dir, Path(project.project_root), role
        )
        if should_block_task(pre_result):
            set_state(
                task_dir, BLOCKED,
                message=f"preCheck blocked: {'; '.join(pre_result.errors)}",
                attempt=attempt,
            )
            return get_state(task_dir)

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
        model=resolved_model,
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
            # PostChecks: run policy evaluation after deliverables confirmed
            if policy_profile is not None:
                post_result = evaluate_task_policy(
                    policy_profile, task_dir, Path(project.project_root), role
                )
                if should_block_task(post_result):
                    set_state(
                        task_dir, BLOCKED,
                        message=f"postCheck blocked: {'; '.join(post_result.errors)}",
                        exit_code=0,
                        session_id=new_session_id,
                        session_mode=session_mode,
                    )
                    return get_state(task_dir)
                if post_result.approval_gate:
                    set_state(
                        task_dir, REVIEW_REQUIRED,
                        message=f"approval gate: {post_result.approval_gate}",
                        exit_code=0,
                        session_id=new_session_id,
                        session_mode=session_mode,
                        last_event_at=telemetry.get("lastEventAt"),
                        tokens=telemetry.get("tokens"),
                    )
                    return get_state(task_dir)

            review_config = meta.get("review") or {}
            review_required = review_config.get("required", True)
            final_state = REVIEW_REQUIRED if review_required else DONE
            final_message = (
                "deliverables complete"
                if review_required
                else "deliverables complete; review skipped"
            )
            set_state(
                task_dir, final_state,
                message=final_message,
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

def run_worker(
    task_dir: str | Path,
    project: ProjectConfig,
    worker: WorkerConfig | None,
    bridge_root: str | Path,
    quiet: bool = False,
) -> dict:
    """Run one worker attempt and always release its scheduler assignment."""
    task_dir = Path(task_dir)
    bridge_root = Path(bridge_root)
    try:
        return _run_worker_inner(task_dir, project, worker, bridge_root, quiet=quiet)
    finally:
        # Manual runs may have no assignment; finish_assignment is a safe no-op.
        # A hard process kill cannot reach finally, so auto-dispatch also
        # reconciles stale records before its next scheduling cycle.
        try:
            from .scheduler.planner import finish_assignment
            finish_assignment(
                bridge_root / "runtime" / "assignments",
                bridge_root / "runtime" / "leases",
                task_dir.name,
            )
        except Exception:
            # Cleanup must never mask the worker result or original failure.
            import logging
            logging.getLogger(__name__).exception(
                "failed to finalize scheduler assignment for %s", task_dir.name
            )

