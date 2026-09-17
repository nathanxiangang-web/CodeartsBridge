# AI生成
"""Workspace manager base class.

A workspace manager handles project workspace preparation:
- existing: use the project root as-is
- local-worktree: create a local git worktree
- remote-worktree: create a remote git worktree via SSH

Transport (local/ssh) handles only command execution.
Workspace handles directory setup, git operations, and cleanup.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WorkspaceResult:
    """Result of workspace preparation."""
    workspace_path: str = ""
    branch: str = ""
    baseline_sha: str = ""
    is_remote: bool = False
    remote_host: str = ""
    # Paths accessible by the worker (may be remote paths)
    repo_path: str = ""
    outbox_path: str = ""
    inbox_path: str = ""
    meta_path: str = ""
    contract_path: str = ""
    instruction_paths: list[str] = field(default_factory=list)
    # Extra info for transport
    extra: dict = field(default_factory=dict)


class WorkspaceManager(ABC):
    """Abstract base for workspace managers."""

    @property
    @abstractmethod
    def workspace_type(self) -> str:
        """Return workspace type identifier."""
        ...

    @abstractmethod
    def prepare(
        self,
        project: Any,
        task_id: str,
        task_dir: Path,
        baseline: str | None = None,
    ) -> WorkspaceResult:
        """Prepare a workspace for a task. Returns workspace info."""
        ...

    def cleanup(
        self,
        task_id: str,
        workspace_result: WorkspaceResult,
    ) -> None:
        """Clean up workspace after task completion. Override if needed."""
        pass

    def salvage(
        self,
        task_id: str,
        workspace_result: WorkspaceResult,
        evidence_dir: Path,
    ) -> str | None:
        """Salvage uncommitted changes on failure. Override if needed."""
        return None
