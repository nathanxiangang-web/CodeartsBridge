# AI生成
"""Integration module: merge completed task work back into the main branch.

Handles:
- Git bundle import from remote workers
- Branch merge with conflict detection
- Conflict resolution assistance
- Integration verification (tests, build checks)
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..git_ops import (
    quote_posix, import_worker_bundle, is_git_repo,
    resolve_baseline,
)

logger = logging.getLogger(__name__)


@dataclass
class IntegrationResult:
    task_id: str
    success: bool
    merged_sha: str = ""
    conflict_files: list[str] = field(default_factory=list)
    error: str = ""
    verification_passed: bool = False


def integrate_task(
    task_id: str,
    project_root: Path,
    task_branch: str,
    target_branch: str = "main",
    host: str | None = None,
    remote_repo: str | None = None,
    baseline_sha: str | None = None,
) -> IntegrationResult:
    """Integrate a completed task's work into the target branch.

    For remote workers: import bundle first, then merge.
    For local workers: merge the task branch directly.
    """
    project_root = Path(project_root)
    if not is_git_repo(project_root):
        return IntegrationResult(
            task_id=task_id, success=False,
            error=f"Not a git repo: {project_root}",
        )

    # Import from remote if applicable
    if host and remote_repo and baseline_sha:
        try:
            import_result = import_worker_bundle(
                host, remote_repo, task_branch,
                project_root, task_id, baseline_sha,
            )
        except Exception as e:
            return IntegrationResult(
                task_id=task_id, success=False,
                error=f"Bundle import failed: {e}",
            )

    # Merge task branch into target
    result = merge_branch(
        project_root, task_branch, target_branch
    )
    return result


def merge_branch(
    project_root: Path,
    task_branch: str,
    target_branch: str = "main",
) -> IntegrationResult:
    """Merge a task branch into the target branch."""
    task_id = task_branch.replace("task/", "")

    # Checkout target branch
    r = subprocess.run(
        ["git", "-C", str(project_root), "checkout", target_branch],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return IntegrationResult(
            task_id=task_id, success=False,
            error=f"Checkout {target_branch} failed: {r.stderr}",
        )

    # Attempt merge
    r = subprocess.run(
        ["git", "-C", str(project_root), "merge", "--no-ff", task_branch],
        capture_output=True, text=True, timeout=60,
    )

    if r.returncode == 0:
        # Get merged SHA
        r2 = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        merged_sha = r2.stdout.strip()
        return IntegrationResult(
            task_id=task_id, success=True,
            merged_sha=merged_sha,
        )

    # Merge failed — check for conflicts
    conflicts = get_conflict_files(project_root)
    if conflicts:
        return IntegrationResult(
            task_id=task_id, success=False,
            conflict_files=conflicts,
            error="Merge conflicts detected",
        )

    # Non-conflict merge failure
    return IntegrationResult(
        task_id=task_id, success=False,
        error=f"Merge failed: {r.stderr}",
    )


def get_conflict_files(project_root: Path) -> list[str]:
    """Get list of files with merge conflicts."""
    r = subprocess.run(
        ["git", "-C", str(project_root), "diff", "--name-only", "--diff-filter=U"],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        return []
    return [f for f in r.stdout.strip().split("\n") if f]


def abort_merge(project_root: Path) -> bool:
    """Abort a failed merge."""
    r = subprocess.run(
        ["git", "-C", str(project_root), "merge", "--abort"],
        capture_output=True, text=True, timeout=15,
    )
    return r.returncode == 0


def verify_integration(
    project_root: Path,
    verify_command: list[str] | None = None,
) -> bool:
    """Run verification (tests/build) after integration.

    Default: run 'git log --oneline -1' to verify repo state.
    Override with a custom command (e.g. ['pytest', '-x']).
    """
    cmd = verify_command or ["git", "log", "--oneline", "-1"]
    try:
        r = subprocess.run(
            cmd, cwd=str(project_root),
            capture_output=True, text=True, timeout=300,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error("Integration verification failed: %s", e)
        return False
