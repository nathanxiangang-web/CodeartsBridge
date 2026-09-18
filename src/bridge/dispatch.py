# AI生成
"""Dispatch planner: select tasks for parallel execution.

Mirrors PowerShell Select-DispatchPlan.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .atomic import read_json, read_json_or_none
from .config import (
    Registry, WorkersRegistry, ProjectConfig, WorkerConfig,
    load_registry, load_workers_registry, get_project,
)
from .state import (
    get_state, set_state,
    READY, QUEUED, STARTING, RUNNING, REVIEW_REQUIRED, DONE,
    FIX_REQUIRED, RETRYABLE, FAILED, BLOCKED, AUTH_REQUIRED,
    CANDIDATE_STATES, ACTIVE_STATES,
)
from .workspace.policy import resolve_workspace_mode


@dataclass
class DispatchItem:
    task_id: str
    directory: str
    project_id: str
    worker_id: str | None = None
    working_dir: str | None = None
    worktree_path: str | None = None
    workspace_mode: str = "existing"
    role: str = "implement"
    status: str = READY
    baseline: str | None = None


@dataclass
class SkippedItem:
    task_id: str
    reason: str


@dataclass
class DispatchPlan:
    plan: list[DispatchItem] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)
    active: list[dict] = field(default_factory=list)


def check_worker_transport_compatibility(worker_transport: str, project_transport: str) -> bool:
    if worker_transport == project_transport:
        return True
    return project_transport == "remote-worktree" and worker_transport == "ssh"


def check_host_affinity(worker: WorkerConfig, project: ProjectConfig) -> bool:
    """Verify worker host is compatible with project's sshHost.

    Rules:
    - local project: any worker transport OK (host not checked)
    - ssh/remote-worktree project with sshHost: worker.host must match sshHost
    - project without sshHost: no affinity check (backward compat)
    """
    if project.transport == "local":
        return True
    if not project.ssh_host:
        return True
    if not worker.host:
        return False
    return worker.host == project.ssh_host


def select_dispatch_plan(
    tasks_root: str | Path,
    bridge_root: str | Path,
    max_workers: int = 4,
) -> DispatchPlan:
    """Select tasks for dispatch. Mirrors Select-DispatchPlan."""
    tasks_root = Path(tasks_root)
    bridge_root = Path(bridge_root)

    # Load registries
    registry = load_registry(bridge_root / "projects.json")
    workers_path = bridge_root / "workers.json"
    workers_reg = None
    if workers_path.is_file():
        workers_reg = load_workers_registry(workers_path)

    # Scan all tasks
    tasks = []
    for d in sorted(tasks_root.iterdir()):
        if not d.is_dir():
            continue
        state_path = d / "state.json"
        meta_path = d / "META.json"
        if not state_path.is_file() or not meta_path.is_file():
            continue
        state = read_json(state_path)
        meta = read_json(meta_path)
        tasks.append({
            "taskId": str(state.get("taskId", d.name)),
            "directory": str(d),
            "status": str(state.get("status") or state.get("state") or ""),
            "projectId": str(meta.get("projectId", "")),
            "meta": meta,
        })

    active = [t for t in tasks if t["status"] in ACTIVE_STATES]
    plan: list[DispatchItem] = []
    skipped: list[SkippedItem] = []

    slots = max_workers - len(active)
    if slots <= 0:
        return DispatchPlan(plan=plan, skipped=skipped, active=active)

    workers = workers_reg.workers if workers_reg else []

    # Track worker usage and active writes
    worker_usage: dict[str, int] = {}
    active_writes: dict[str, int] = {}
    active_any: dict[str, int] = {}

    for a in active:
        meta = a["meta"]
        wid = meta.get("workerId")
        if wid:
            worker_usage[wid] = worker_usage.get(wid, 0) + 1

        try:
            proj = get_project(registry, a["projectId"])
            wd = str(Path(proj.project_root).resolve()) if proj.transport == "local" else proj.project_root
        except ValueError:
            wd = None

        role = meta.get("role", "implement")
        if wd:
            idle_key = f"{proj.ssh_host}::{wd}" if getattr(proj, "ssh_host", None) else wd
            active_any[idle_key] = active_any.get(idle_key, 0) + 1
            if role == "implement":
                active_writes[idle_key] = active_writes.get(idle_key, 0) + 1

    # Process candidates
    candidates = sorted(
        [t for t in tasks if t["status"] in CANDIDATE_STATES],
        key=lambda t: t["taskId"],
    )

    for c in candidates:
        if len(plan) >= slots:
            break

        meta = c["meta"]

        # Check dependencies
        deps = meta.get("dependsOn", [])
        dep_ok = True
        for dep in deps:
            dep_task = [t for t in tasks if t["taskId"] == dep]
            if not dep_task or dep_task[0]["status"] != DONE:
                dep_ok = False
                break
        if not dep_ok:
            skipped.append(SkippedItem(c["taskId"], "dependencies not DONE"))
            continue

        role = meta.get("role", "implement")

        # Get project
        try:
            project = get_project(registry, c["projectId"])
        except ValueError:
            skipped.append(SkippedItem(c["taskId"], f"project not found: {c['projectId']}"))
            continue

        # Select worker
        worker = None
        explicit_worker_id = meta.get("workerId")

        if explicit_worker_id:
            matches = [w for w in workers if w.id == explicit_worker_id]
            if not matches:
                skipped.append(SkippedItem(c["taskId"], f"explicit worker not registered: {explicit_worker_id}"))
                continue
            worker = matches[0]
            if not worker.enabled:
                skipped.append(SkippedItem(c["taskId"], f"explicit worker disabled: {explicit_worker_id}"))
                continue
            if worker_usage.get(worker.id, 0) >= worker.concurrency_limit:
                skipped.append(SkippedItem(c["taskId"], f"explicit worker at capacity: {explicit_worker_id}"))
                continue
            if worker.capabilities and role not in worker.capabilities:
                skipped.append(SkippedItem(c["taskId"], f"explicit worker lacks capability {role}: {explicit_worker_id}"))
                continue
            if not check_worker_transport_compatibility(worker.transport, project.transport):
                skipped.append(SkippedItem(c["taskId"], f"explicit worker transport mismatch: {worker.transport}/{project.transport}"))
                continue
            if not check_host_affinity(worker, project):
                skipped.append(SkippedItem(c["taskId"], f"explicit worker host mismatch: {worker.host}/{project.ssh_host}"))
                continue
        else:
            candidates_w = sorted(
                [w for w in workers if w.enabled
                 and check_worker_transport_compatibility(w.transport, project.transport)
                 and check_host_affinity(w, project)],
                key=lambda w: w.id,
            )
            chosen = None
            for w in candidates_w:
                if worker_usage.get(w.id, 0) >= w.concurrency_limit:
                    continue
                if w.capabilities and role not in w.capabilities:
                    continue
                chosen = w
                break
            if not chosen:
                skipped.append(SkippedItem(c["taskId"], f"no available worker for transport {project.transport} and role {role}"))
                continue
            worker = chosen

        # Resolve the same workspace contract used by Worker runtime.
        execution = meta.get("execution") if isinstance(meta.get("execution"), dict) else {}
        requested_workspace = execution.get(
            "workspace", meta.get("workspaceMode", "auto")
        )
        try:
            mode = resolve_workspace_mode(requested_workspace, project.transport)
        except ValueError as exc:
            skipped.append(SkippedItem(c["taskId"], f"workspace policy: {exc}"))
            continue

        project_root = str(Path(project.project_root).resolve()) if project.transport == "local" else project.project_root
        idle_key = f"{project.ssh_host}::{project_root}" if project.ssh_host else project_root

        working_dir = None
        worktree_path = None
        skip_reason = None

        if mode == "local-worktree":
            working_dir = str(Path(bridge_root) / "runtime" / "worktrees" / c["taskId"])
            worktree_path = working_dir
        elif mode == "remote-worktree":
            # RemoteWorktreeTransport owns remote workspace preparation.
            working_dir = project.project_root
        elif mode == "existing":
            if active_any.get(idle_key, 0) > 0:
                skip_reason = f"existing mode requires idle project: {idle_key}"
            else:
                working_dir = project_root
        else:
            skip_reason = f"unsupported effective workspaceMode: {mode}"

        if skip_reason:
            skipped.append(SkippedItem(c["taskId"], skip_reason))
            continue

        item = DispatchItem(
            task_id=c["taskId"],
            directory=c["directory"],
            project_id=c["projectId"],
            worker_id=worker.id,
            working_dir=working_dir,
            worktree_path=worktree_path,
            workspace_mode=mode,
            role=role,
            status=c["status"],
            baseline=meta.get("baseline"),
        )
        plan.append(item)

        # Update tracking
        worker_usage[worker.id] = worker_usage.get(worker.id, 0) + 1
        if mode == "existing":
            active_any[idle_key] = active_any.get(idle_key, 0) + 1
        if role == "implement" and mode == "existing":
            active_writes[idle_key] = active_writes.get(idle_key, 0) + 1

    return DispatchPlan(plan=plan, skipped=skipped, active=active)


@dataclass
class DispatchExecutionResult:
    """Result of executing a dispatch plan."""
    plan: DispatchPlan
    spawned: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def execute_dispatch(
    tasks_root: str | Path,
    bridge_root: str | Path,
    max_workers: int = 4,
    dry_run: bool = False,
    spawn_workers: bool = True,
) -> DispatchExecutionResult:
    """Unified dispatch execution service.

    Both CLI and daemon call this function. It:
    1. Plans dispatch via select_dispatch_plan
    2. Sets QUEUED state for each planned task
    3. Spawns worker processes (unless dry_run or spawn_workers=False)
    4. On spawn failure, reverts to READY to avoid permanent QUEUED
    """
    plan = select_dispatch_plan(tasks_root, bridge_root, max_workers=max_workers)

    if dry_run or not plan.plan:
        return DispatchExecutionResult(plan=plan)

    result = DispatchExecutionResult(plan=plan)

    for item in plan.plan:
        tdir = Path(item.directory)

        # Race protection: skip if no longer candidate
        current = get_state(tdir)
        if current.get("status") not in CANDIDATE_STATES:
            result.failed.append((item.task_id, f"no longer candidate: {current.get('status')}"))
            continue

        # Set QUEUED
        set_state(
            tdir, QUEUED,
            message=f"dispatched to {item.worker_id}",
            assigned_worker_id=item.worker_id,
        )

        if spawn_workers:
            try:
                subprocess.Popen(
                    [sys.executable, "-m", "bridge.cli", "run", "-t", item.task_id],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                result.spawned.append(item.task_id)
            except Exception as e:
                # Spawn failed: revert to READY to avoid permanent QUEUED
                set_state(
                    tdir, READY,
                    message=f"spawn failed: {e}",
                    assigned_worker_id="",
                )
                result.failed.append((item.task_id, str(e)))

    return result