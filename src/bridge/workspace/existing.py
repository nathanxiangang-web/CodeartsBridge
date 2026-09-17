# AI生成
"""Existing workspace manager — use the project root as-is.

No git worktree, no remote setup. The worker operates directly
in the project's configured root directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import WorkspaceManager, WorkspaceResult


class ExistingWorkspace(WorkspaceManager):
    """Use the project root directly as the workspace."""

    @property
    def workspace_type(self) -> str:
        return "existing"

    def prepare(
        self,
        project: Any,
        task_id: str,
        task_dir: Path,
        baseline: str | None = None,
    ) -> WorkspaceResult:
        project_root = getattr(project, "project_root", "")
        return WorkspaceResult(
            workspace_path=project_root,
            repo_path=project_root,
            is_remote=False,
            extra={"transport": "local"},
        )
