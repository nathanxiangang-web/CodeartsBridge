"""Workspace execution policy.

Maps the task-level workspace request to an effective mode supported by the
project transport. Explicit isolation requests are never silently downgraded.
"""

from __future__ import annotations


VALID_WORKSPACE_REQUESTS = {
    "auto",
    "isolated",
    "existing",
    "worktree",
    "local-worktree",
    "remote-worktree",
    "shared-readonly",
}


def normalize_workspace_request(value: str | None) -> str:
    request = str(value or "auto").strip().lower()
    if request not in VALID_WORKSPACE_REQUESTS:
        allowed = ", ".join(sorted(VALID_WORKSPACE_REQUESTS))
        raise ValueError(f"Unsupported workspace mode: {request}; expected one of {allowed}")
    return request


def resolve_workspace_mode(requested: str | None, project_transport: str) -> str:
    """Resolve a task workspace request for a project transport."""
    request = normalize_workspace_request(requested)
    transport = str(project_transport or "local").strip().lower()

    if request == "auto":
        if transport == "local":
            return "local-worktree"
        if transport == "remote-worktree":
            return "remote-worktree"
        if transport in {"ssh", "ssh-shell"}:
            return "existing"
        raise ValueError(f"Unsupported project transport for workspace auto mode: {transport}")

    if request in {"isolated", "worktree", "local-worktree"}:
        if transport == "local":
            return "local-worktree"
        if transport == "remote-worktree":
            return "remote-worktree"
        raise ValueError(
            f"Workspace {request} requires isolation, but transport {transport} "
            "does not provide an isolated workspace; use remote-worktree"
        )

    if request == "remote-worktree":
        if transport != "remote-worktree":
            raise ValueError(
                f"Workspace remote-worktree requires project transport remote-worktree, got {transport}"
            )
        return "remote-worktree"

    if request == "existing":
        if transport == "remote-worktree":
            raise ValueError(
                "Workspace existing is incompatible with remote-worktree transport"
            )
        if transport not in {"local", "ssh", "ssh-shell"}:
            raise ValueError(f"Unsupported project transport for existing workspace: {transport}")
        return "existing"

    if request == "shared-readonly":
        raise ValueError(
            "Workspace shared-readonly is not enforceable by the current Worker transports"
        )

    raise ValueError(f"Unsupported workspace mode: {request}")
