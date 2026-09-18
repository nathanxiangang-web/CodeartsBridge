# AI生成
"""Worker process management: run a single task via the appropriate transport.

Mirrors PowerShell Invoke-LocalWorker/Invoke-SshWorker dispatch + Complete-WorkerRun.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .codearts import parse_codearts_json_lines, REQUIRED_MODEL, resolve_model
from .atomic import atomic_write_text
from .config import ProjectConfig, WorkerConfig
from .state import (
    get_state, set_state, READY, QUEUED, STARTING, RUNNING,
    REVIEW_REQUIRED, DONE, BLOCKED, FAILED, RETRYABLE,
    ASSISTANCE_REQUIRED, AUTH_REQUIRED, FIX_REQUIRED,
)
from .task import get_meta, get_instruction_context, archive_previous_outbox
from .transport import LocalTransport, SshTransport, SshShellTransport, RemoteWorktreeTransport
from .workspace import LocalWorktreeWorkspace
from .workspace.policy import resolve_workspace_mode
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


def _capture_isolated_commit(
    task_dir: Path,
    effective_project: ProjectConfig,
    workspace_mode: str,
    result: Any,
    workspace_baseline: str | None,
) -> tuple[str | None, str | None]:
    """Capture the commit that integration must consume for isolated workspaces."""
    if getattr(result, "import_error", None):
        return None, f"workspace result import failed: {result.import_error}"

    commit_sha = getattr(result, "imported_sha", None)

    if workspace_mode == "local-worktree":
        try:
            proc = subprocess.run(
                ["git", "-C", str(effective_project.project_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"cannot resolve local worktree commit: {exc}"
        if proc.returncode != 0 or not proc.stdout.strip():
            return None, "cannot resolve local worktree commit"
        commit_sha = proc.stdout.strip()
        if workspace_baseline and commit_sha == workspace_baseline:
            return None, "isolated local workspace produced no new commit"

    elif workspace_mode == "remote-worktree":
        if not commit_sha:
            return None, "remote-worktree completed without an imported result commit"

    if commit_sha:
        outbox = task_dir / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        atomic_write_text(outbox / "COMMIT.sha", f"{commit_sha}\n")

    return commit_sha, None


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

    # Resolve the task workspace before execution. Explicit isolation requests
    # must never be silently downgraded to a shared project directory.
    execution = meta.get("execution") or {}
    requested_workspace = execution.get(
        "workspace", meta.get("workspaceMode", "auto")
    )
    baseline = meta.get("baseline")
    workspace_baseline = baseline
    try:
        workspace_mode = resolve_workspace_mode(
            requested_workspace, project.transport
        )
    except ValueError as exc:
        set_state(
            task_dir, BLOCKED,
            message=f"workspace policy blocked: {exc}",
            attempt=attempt,
        )
        return get_state(task_dir)

    effective_project = project
    workspace_path = project.project_root
    if workspace_mode == "local-worktree":
        try:
            workspace = LocalWorktreeWorkspace(
                worktree_root=Path(bridge_root) / "runtime" / "worktrees"
            ).prepare(
                project=project,
                task_id=task_id,
                task_dir=task_dir,
                baseline=baseline,
            )
            effective_project = replace(project, project_root=workspace.repo_path)
            workspace_path = workspace.repo_path
            workspace_baseline = workspace.baseline_sha
        except Exception as exc:
            set_state(
                task_dir, BLOCKED,
                message=f"workspace preparation failed: {exc}",
                attempt=attempt,
                workspace_mode=workspace_mode,
            )
            return get_state(task_dir)

    # Set RUNNING only after the execution location is resolved.
    set_state(
        task_dir, RUNNING,
        message=f"attempt {attempt} running",
        process_id=__import__("os").getpid(),
        workspace_mode=workspace_mode,
        workspace_path=str(workspace_path),
    )

    # Calculate timeouts from META v2 execution config.
    # Top-level fields remain a compatibility fallback for legacy tasks.
    timeout_seconds = int(
        execution.get("hardTimeoutMinutes", meta.get("hardTimeoutMinutes", 15))
    ) * 60
    soft_timeout_seconds = int(
        execution.get("softTimeoutMinutes", meta.get("softTimeoutMinutes", 12))
    ) * 60
    mode = effective_project.run_mode or "auto"
    role = meta.get("role", "implement")
    resolved_model = resolve_model(
        role=role, worker=worker, project=effective_project
    )

    # Load policy profile (optional)
    policy_profile = load_profile_for_project(
        Path(bridge_root), effective_project.id
    )

    # PreChecks: run before worker execution
    if policy_profile is not None:
        pre_result = evaluate_pre_checks(
            policy_profile, task_dir, Path(effective_project.project_root), role
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
        project=effective_project,
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
        timeout_msg = "hard timeout — assistance required (re-plan needed)"
        if result.soft_checkpointed:
            timeout_msg = "hard timeout after soft checkpoint — assistance required (re-plan needed)"
        set_state(
            task_dir, ASSISTANCE_REQUIRED,
            message=timeout_msg,
            exit_code=result.exit_code,
            session_id=new_session_id,
            session_mode=session_mode,
            last_event_at=telemetry.get("lastEventAt"),
            tokens=telemetry.get("tokens"),
        )
    elif result.exit_code == 0:
        # Check deliverables
        outbox = task_dir / "outbox"
        has_result = (outbox / "RESULT.md").is_file()
        has_tests = (outbox / "TESTS.md").is_file()
        has_diff = (outbox / "DIFF.stat").is_file()

        if has_result and has_tests and has_diff:
            commit_sha, commit_error = _capture_isolated_commit(
                task_dir=task_dir,
                effective_project=effective_project,
                workspace_mode=workspace_mode,
                result=result,
                workspace_baseline=(
                    getattr(result, "baseline_sha", None) or workspace_baseline
                ),
            )
            if commit_error:
                set_state(
                    task_dir, FAILED,
                    message=commit_error,
                    exit_code=0,
                    session_id=new_session_id,
                    session_mode=session_mode,
                )
                return get_state(task_dir)

            # PostChecks: run policy evaluation after deliverables confirmed
            if policy_profile is not None:
                post_result = evaluate_task_policy(
                    policy_profile, task_dir, Path(effective_project.project_root), role
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
                        commit_sha=commit_sha,
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
                commit_sha=commit_sha,
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

