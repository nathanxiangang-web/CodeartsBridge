# AI生成
"""Workspace management package for CodeartsBridge.

Separates workspace preparation (existing, local-worktree, remote-worktree)
from transport (local, ssh). Transport handles command execution;
workspace handles directory setup, git operations, and cleanup.
"""

from .base import WorkspaceManager, WorkspaceResult
from .existing import ExistingWorkspace
from .local_worktree import LocalWorktreeWorkspace
from .remote_worktree import RemoteWorktreeWorkspace


def create_workspace_manager(workspace_type: str, **kwargs) -> WorkspaceManager:
    """Factory: create a workspace manager by type string."""
    if workspace_type == "existing":
        return ExistingWorkspace()
    elif workspace_type == "local-worktree" or workspace_type == "worktree":
        return LocalWorktreeWorkspace(**kwargs)
    elif workspace_type == "remote-worktree":
        return RemoteWorktreeWorkspace()
    else:
        raise ValueError(f"Unknown workspace type: {workspace_type}")


__all__ = [
    "WorkspaceManager", "WorkspaceResult",
    "ExistingWorkspace", "LocalWorktreeWorkspace", "RemoteWorktreeWorkspace",
    "create_workspace_manager",
]
