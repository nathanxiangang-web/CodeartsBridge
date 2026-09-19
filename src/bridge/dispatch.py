# AI生成
"""Transport compatibility helpers for dispatch decisions.

The legacy parallel planner (select_dispatch_plan / execute_dispatch) has been
removed in favor of bridge.auto_dispatch + bridge.scheduler.planner, which is
the single dispatch path used by both the CLI and pipeline.py.
"""

from __future__ import annotations

from .config import ProjectConfig, WorkerConfig


def check_worker_transport_compatibility(worker_transport: str, project_transport: str) -> bool:
    if worker_transport == project_transport:
        return True
    if project_transport == "remote-worktree" and worker_transport == "ssh":
        return True
    if worker_transport == "agent":
        return True
    return False


def check_host_affinity(worker: WorkerConfig, project: ProjectConfig) -> bool:
    """Verify worker host is compatible with project's sshHost.

    Rules:
    - local project: any worker transport OK (host not checked)
    - agent transport: any project OK (HTTP, not host-bound)
    - ssh/remote-worktree project with sshHost: worker.host must match sshHost
    - project without sshHost: no affinity check (backward compat)
    """
    if project.transport == "local":
        return True
    if worker.transport == "agent":
        return True
    if not project.ssh_host:
        return True
    if not worker.host:
        return False
    return worker.host == project.ssh_host
