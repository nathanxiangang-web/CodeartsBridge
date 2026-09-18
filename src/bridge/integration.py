# AI生成
"""Integration module: merge completed task work back into the main branch.

P2-03 integration automation. Provides cherry-pick based integration of
DONE-state tasks into the main branch with post-merge verification.

Key functions:
    integrate_task(task_id, bridge_root) -> IntegrationResult
    integrate_loop(bridge_root) -> list[IntegrationResult]

Legacy functions (backward compat with v2 integration_service):
    integrate_task_branch(...) -> IntegrationResult
    merge_branch(...) -> IntegrationResult
    get_conflict_files(project_root) -> list[str]
    abort_merge(project_root) -> bool
    verify_integration(project_root, verify_command) -> bool
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .atomic import atomic_write_json, read_json_or_none
from .state import (
    get_state, set_state,
    DONE, INTEGRATION_FAILED,
)
from .config import load_registry, get_project

import logging
logger = logging.getLogger(__name__)

DEFAULT_VERIFY_COMMAND: list[str] = [
    sys.executable, "-m", "pytest", "tests/e2e/", "-q",
]

_BASELINE_REGISTRY_REL = Path("runtime") / "integration" / "baselines.json"


@dataclass
class IntegrationResult:
    """Result of an integration attempt."""
    task_id: str
    success: bool
    merged_sha: str = ""
    reverted: bool = False
    baseline_updated: bool = False
    verification_passed: bool = False
    error: str = ""
    conflict_files: list[str] = field(default_factory=list)
    dry_run: bool = False
    commit_sha: str = ""


def _load_baseline_registry(bridge_root: Path) -> dict:
    path = bridge_root / _BASELINE_REGISTRY_REL
    data = read_json_or_none(path)
    if data is None:
        return {}
    return data


def _save_baseline_registry(bridge_root: Path, registry: dict) -> None:
    path = bridge_root / _BASELINE_REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, registry)


def update_baseline_sha(bridge_root: Path, project_id: str, sha: str) -> None:
    registry = _load_baseline_registry(bridge_root)
    registry[project_id] = sha
    _save_baseline_registry(bridge_root, registry)


def get_baseline_sha(bridge_root: Path, project_id: str) -> str:
    registry = _load_baseline_registry(bridge_root)
    return registry.get(project_id, "")


def _run_git(args: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _get_head_sha(project_root: Path) -> str:
    r = _run_git(["rev-parse", "HEAD"], project_root, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else ""


def _resolve_task_commit(task_dir: Path, state: dict, meta: dict) -> str:
    """Resolve the commit SHA to cherry-pick for this task."""
    sha = (
        state.get("commitSha")
        or state.get("headSha")
        or meta.get("commitSha")
        or meta.get("headSha")
        or meta.get("baseline")
    )
    if sha:
        return sha
    commit_file = task_dir / "outbox" / "COMMIT.sha"
    if commit_file.is_file():
        text = commit_file.read_text(encoding="utf-8").strip()
        if text:
            return text
    return ""


def _resolve_project_root(bridge_root: Path, meta: dict) -> Path:
    """Resolve the project root directory from META.json projectId."""
    project_id = meta.get("projectId", "")
    if not project_id:
        return bridge_root
    projects_path = bridge_root / "projects.json"
    if not projects_path.is_file():
        return bridge_root
    try:
        registry = load_registry(projects_path)
        project = get_project(registry, project_id)
        root = getattr(project, "project_root", "") or ""
        if root:
            return Path(root)
    except Exception:
        pass
    return bridge_root


def _run_focused_tests(project_root: Path, verify_command: list[str] | None = None) -> bool:
    """Run focused tests after merge. Returns True on pass."""
    cmd = verify_command if verify_command is not None else DEFAULT_VERIFY_COMMAND
    if not cmd:
        return True
    try:
        r = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode != 0:
            logger.warning(
                "Focused tests failed for %s: %s",
                project_root, r.stderr[:500] if r.stderr else r.stdout[:500],
            )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error("Focused test execution error: %s", e)
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def integrate_task(
    task_id: str,
    bridge_root: Path,
    *,
    dry_run: bool = False,
    verify_command: list[str] | None = None,
    target_branch: str = "main",
) -> IntegrationResult:
    """Integrate a DONE-state task into the main branch via cherry-pick.

    Steps:
    1. Pre-merge gate: verify task state is DONE
    2. Resolve the task commit SHA
    3. Cherry-pick the commit into target_branch
    4. Post-merge: run focused tests
    5. On pass: update baseline SHA in registry
    6. On failure: revert merge, mark task INTEGRATION_FAILED
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id

    if not task_dir.is_dir():
        return IntegrationResult(
            task_id=task_id, success=False,
            error=f"Task directory not found: {task_dir}",
        )

    state = get_state(task_dir)
    meta = read_json_or_none(task_dir / "META.json") or {}
    current_state = state.get("status") or state.get("state", "")

    if current_state != DONE:
        return IntegrationResult(
            task_id=task_id, success=False,
            error=f"Task state is {current_state}, must be {DONE} to integrate",
        )

    commit_sha = _resolve_task_commit(task_dir, state, meta)
    if not commit_sha:
        return IntegrationResult(
            task_id=task_id, success=False,
            error="No commit SHA found for task (set commitSha in state.json or META.json)",
        )

    project_root = _resolve_project_root(bridge_root, meta)

    if dry_run:
        return IntegrationResult(
            task_id=task_id, success=True,
            dry_run=True,
            commit_sha=commit_sha,
            merged_sha=_get_head_sha(project_root),
        )

    pre_merge_sha = _get_head_sha(project_root)

    r = _run_git(["checkout", target_branch], project_root, timeout=30)
    if r.returncode != 0:
        return IntegrationResult(
            task_id=task_id, success=False,
            error=f"Checkout {target_branch} failed: {r.stderr.strip()}",
            commit_sha=commit_sha,
        )

    r = _run_git(["cherry-pick", commit_sha], project_root, timeout=60)
    if r.returncode != 0:
        conflicts = get_conflict_files(project_root)
        _run_git(["cherry-pick", "--abort"], project_root, timeout=15)
        set_state(task_dir, INTEGRATION_FAILED, message=f"cherry-pick failed: {r.stderr.strip()[:200]}")
        return IntegrationResult(
            task_id=task_id, success=False,
            error=f"Cherry-pick failed: {r.stderr.strip()}",
            conflict_files=conflicts,
            reverted=True,
            commit_sha=commit_sha,
        )

    merged_sha = _get_head_sha(project_root)

    tests_passed = _run_focused_tests(project_root, verify_command)
    if not tests_passed:
        _run_git(["reset", "--hard", pre_merge_sha], project_root, timeout=30)
        set_state(task_dir, INTEGRATION_FAILED, message="post-merge tests failed, merge reverted")
        return IntegrationResult(
            task_id=task_id, success=False,
            error="Post-merge focused tests failed",
            verification_passed=False,
            reverted=True,
            merged_sha=merged_sha,
            commit_sha=commit_sha,
        )

    project_id = meta.get("projectId", "default")
    update_baseline_sha(bridge_root, project_id, merged_sha)

    state["integratedSha"] = merged_sha
    state["integratedAt"] = _now_iso()
    atomic_write_json(task_dir / "state.json", state)

    return IntegrationResult(
        task_id=task_id, success=True,
        merged_sha=merged_sha,
        verification_passed=True,
        baseline_updated=True,
        commit_sha=commit_sha,
    )


def integrate_loop(
    bridge_root: Path,
    *,
    dry_run: bool = False,
    verify_command: list[str] | None = None,
) -> list[IntegrationResult]:
    """Scan for DONE tasks not yet integrated and integrate them serially.

    A task is eligible if:
    - State is DONE
    - state.json does not have "integratedSha" set

    Integrations are serialized: one at a time, no parallel merges.
    """
    bridge_root = Path(bridge_root)
    tasks_root = bridge_root / "tasks"
    results: list[IntegrationResult] = []

    if not tasks_root.is_dir():
        return results

    eligible: list[str] = []
    for task_dir in sorted(tasks_root.iterdir()):
        if not task_dir.is_dir():
            continue
        state = get_state(task_dir)
        status = state.get("status") or state.get("state", "")
        if status != DONE:
            continue
        if state.get("integratedSha"):
            continue
        eligible.append(task_dir.name)

    for task_id in eligible:
        result = integrate_task(
            task_id, bridge_root,
            dry_run=dry_run,
            verify_command=verify_command,
        )
        results.append(result)
        if not result.success and not result.reverted:
            logger.warning("Stopping loop: %s failed without clean revert", task_id)
            break

    return results


def integrate_task_branch(
    task_id: str,
    project_root: Path,
    task_branch: str,
    target_branch: str = "main",
    host: str | None = None,
    remote_repo: str | None = None,
    baseline_sha: str | None = None,
) -> IntegrationResult:
    """Integrate a completed task into the target branch (legacy).

    For remote workers: import bundle first, then merge.
    For local workers: merge the task branch directly.
    """
    project_root = Path(project_root)

    from .git_ops import is_git_repo, import_worker_bundle

    if not is_git_repo(project_root):
        return IntegrationResult(
            task_id=task_id, success=False,
            error=f"Not a git repo: {project_root}",
        )

    if host and remote_repo and baseline_sha:
        try:
            import_worker_bundle(
                host, remote_repo, task_branch,
                project_root, task_id, baseline_sha,
            )
        except Exception as e:
            return IntegrationResult(
                task_id=task_id, success=False,
                error=f"Bundle import failed: {e}",
            )

    result = merge_branch(project_root, task_branch, target_branch)
    return result


def merge_branch(
    project_root: Path,
    task_branch: str,
    target_branch: str = "main",
) -> IntegrationResult:
    """Merge a task branch into the target branch (legacy)."""
    task_id = task_branch.replace("task/", "")

    r = subprocess.run(
        ["git", "-C", str(project_root), "checkout", target_branch],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return IntegrationResult(
            task_id=task_id, success=False,
            error=f"Checkout {target_branch} failed: {r.stderr}",
        )

    r = subprocess.run(
        ["git", "-C", str(project_root), "merge", "--no-ff", task_branch],
        capture_output=True, text=True, timeout=60,
    )

    if r.returncode == 0:
        merged_sha = _get_head_sha(project_root)
        return IntegrationResult(
            task_id=task_id, success=True,
            merged_sha=merged_sha,
        )

    conflicts = get_conflict_files(project_root)
    if conflicts:
        return IntegrationResult(
            task_id=task_id, success=False,
            conflict_files=conflicts,
            error="Merge conflicts detected",
        )

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

    Default: run git log --oneline -1 to verify repo state.
    Override with a custom command (e.g. [pytest, -x]).
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
