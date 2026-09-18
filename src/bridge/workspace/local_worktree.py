# AI生成
"""Local git worktree workspace manager.

Creates a local git worktree for each task, providing isolation
without remote SSH overhead.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..git_ops import is_git_repo, resolve_baseline, quote_posix
from .base import WorkspaceManager, WorkspaceResult


class LocalWorktreeWorkspace(WorkspaceManager):
    """Create a local git worktree for task isolation."""

    def __init__(self, worktree_root: Path | None = None):
        self.worktree_root = worktree_root

    @property
    def workspace_type(self) -> str:
        return "local-worktree"

    def prepare(
        self,
        project: Any,
        task_id: str,
        task_dir: Path,
        baseline: str | None = None,
    ) -> WorkspaceResult:
        project_root = Path(getattr(project, "project_root", ""))
        if not is_git_repo(project_root):
            raise ValueError(f"Not a git repo: {project_root}")

        baseline_sha = resolve_baseline(project_root, baseline)
        branch = f"task/{task_id}"

        wt_root = self.worktree_root or (task_dir / "worktree")
        wt_root.mkdir(parents=True, exist_ok=True)
        wt_path = wt_root / task_id

        # Reuse an existing task worktree on retry/restart. A task keeps one
        # stable isolated branch until integration succeeds and cleans it up.
        if wt_path.is_dir() and is_git_repo(wt_path):
            head = subprocess.run(
                ["git", "-C", str(wt_path), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            current_sha = head.stdout.strip() if head.returncode == 0 else baseline_sha
            return WorkspaceResult(
                workspace_path=str(wt_path),
                branch=branch,
                baseline_sha=current_sha or baseline_sha,
                repo_path=str(wt_path),
                is_remote=False,
                extra={"transport": "local", "reused": True},
            )

        # If a previous worktree was pruned but the task branch remains, attach
        # the existing branch rather than trying to recreate it with -b.
        branch_check = subprocess.run(
            ["git", "-C", str(project_root), "show-ref", "--verify", "--quiet",
             f"refs/heads/{branch}"],
            capture_output=True, text=True, timeout=10,
        )
        if branch_check.returncode == 0:
            cmd = [
                "git", "-C", str(project_root),
                "worktree", "add", str(wt_path), branch,
            ]
        else:
            cmd = [
                "git", "-C", str(project_root),
                "worktree", "add", "-b", branch,
                str(wt_path), baseline_sha,
            ]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise ValueError(f"Worktree creation failed: {r.stderr}")

        return WorkspaceResult(
            workspace_path=str(wt_path),
            branch=branch,
            baseline_sha=baseline_sha,
            repo_path=str(wt_path),
            is_remote=False,
            extra={"transport": "local", "reused": False},
        )

    def cleanup(
        self,
        task_id: str,
        workspace_result: WorkspaceResult,
    ) -> None:
        wt_path = workspace_result.workspace_path
        branch = workspace_result.branch
        if not wt_path:
            return

        # Remove worktree
        subprocess.run(
            ["git", "worktree", "remove", "--force", wt_path],
            capture_output=True, timeout=15,
        )
        # Delete branch
        if branch:
            subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True, timeout=10,
            )
