# AI生成
"""Conflict detection and resolution for parallel task integration.

When multiple Workers produce changes to overlapping files, the integration
step may fail. This module detects file-level conflicts before merge,
auto-rebases non-conflicting patches, and marks conflicting tasks.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .atomic import atomic_write_json, atomic_write_text, read_json_or_none
from .state import get_state, set_state, DONE, FAILED


CONFLICT = "CONFLICT"


@dataclass
class ConflictResult:
    """Result of conflict detection for a task."""
    task_id: str
    conflict: bool = False
    conflicting_files: list[str] = field(default_factory=list)
    task_files: list[str] = field(default_factory=list)
    main_files: list[str] = field(default_factory=list)
    context: str = ""


@dataclass
class RebaseResult:
    """Result of an auto-rebase attempt."""
    task_id: str
    success: bool = False
    message: str = ""


@dataclass
class ConflictResolution:
    """Result of handling a conflict."""
    task_id: str
    marked_conflict: bool = False
    conflict_diff_written: bool = False
    event_written: bool = False


def _run_git(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args, capture_output=True, text=True, timeout=timeout, cwd=str(cwd)
    )


def _get_changed_files(commit: str, cwd: Path) -> list[str]:
    r = _run_git(["diff", "--name-only", f"{commit}^..{commit}"], cwd)
    if r.returncode != 0:
        return []
    return [f.strip() for f in r.stdout.splitlines() if f.strip()]


def _get_main_files(project_root: Path, since_commit: str | None = None) -> list[str]:
    if since_commit:
        r = _run_git(["diff", "--name-only", f"{since_commit}..HEAD"], project_root)
    else:
        r = _run_git(["diff", "--name-only", "HEAD"], project_root)
    if r.returncode != 0:
        return []
    return [f.strip() for f in r.stdout.splitlines() if f.strip()]


def detect_conflict(task_id: str, bridge_root: Path) -> ConflictResult:
    """Detect file-level conflict between a task commit and current main.

    Compares the set of files changed by the task commit with files
    changed on main since the task's baseline. Overlapping files = conflict.
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    meta = read_json_or_none(task_dir / "META.json")
    if not meta:
        return ConflictResult(task_id=task_id, context="META.json not found")

    state = get_state(task_dir)
    commit_sha = state.get("commitSha") or meta.get("commitSha")
    if not commit_sha:
        return ConflictResult(task_id=task_id, context="no commit SHA in state/meta")

    project_root = _resolve_project_root(bridge_root, meta)
    if not project_root:
        return ConflictResult(task_id=task_id, context="cannot resolve project root")

    task_files = set(_get_changed_files(commit_sha, project_root))
    main_files = set(_get_main_files(project_root, since_commit=commit_sha))
    overlapping = task_files & main_files

    return ConflictResult(
        task_id=task_id,
        conflict=len(overlapping) > 0,
        conflicting_files=sorted(overlapping),
        task_files=sorted(task_files),
        main_files=sorted(main_files),
        context=f"overlap: {sorted(overlapping)}" if overlapping else "disjoint",
    )


def auto_rebase(task_id: str, bridge_root: Path) -> RebaseResult:
    """Attempt to rebase a task commit onto current main.

    Only succeeds if there are no file-level conflicts.
    """
    bridge_root = Path(bridge_root)
    cr = detect_conflict(task_id, bridge_root)
    if cr.conflict:
        return RebaseResult(task_id=task_id, success=False, message=f"conflict on: {cr.conflicting_files}")

    task_dir = bridge_root / "tasks" / task_id
    state = get_state(task_dir)
    commit_sha = state.get("commitSha")
    if not commit_sha:
        return RebaseResult(task_id=task_id, success=False, message="no commit SHA")

    meta = read_json_or_none(task_dir / "META.json")
    project_root = _resolve_project_root(bridge_root, meta or {})
    if not project_root:
        return RebaseResult(task_id=task_id, success=False, message="no project root")

    r = _run_git(["cherry-pick", "--no-commit", commit_sha], project_root)
    if r.returncode == 0:
        return RebaseResult(task_id=task_id, success=True, message="cherry-pick clean")
    _run_git(["cherry-pick", "--abort"], project_root)
    return RebaseResult(task_id=task_id, success=False, message=r.stderr[:200])


def handle_conflict(task_id: str, bridge_root: Path) -> ConflictResolution:
    """Mark a task as CONFLICT, capture diff, write event.

    1. Set task state to CONFLICT
    2. Write conflict.diff to outbox
    3. Write CONFLICT.md to outbox
    4. Append event to events.jsonl
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    outbox = task_dir / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)

    resolution = ConflictResolution(task_id=task_id)

    cr = detect_conflict(task_id, bridge_root)
    if not cr.conflict:
        return resolution

    set_state(task_dir, CONFLICT)
    resolution.marked_conflict = True

    meta = read_json_or_none(task_dir / "META.json")
    project_root = _resolve_project_root(bridge_root, meta or {})
    state = get_state(task_dir)
    commit_sha = state.get("commitSha") or (meta or {}).get("commitSha")

    if commit_sha and project_root:
        r = _run_git(["diff", f"{commit_sha}^..{commit_sha}"], project_root)
        if r.returncode == 0:
            atomic_write_text(outbox / "conflict.diff", r.stdout)
            resolution.conflict_diff_written = True

    conflict_md = f"""# CONFLICT: {task_id}

## Conflicting Files
{chr(10).join(f'- {f}' for f in cr.conflicting_files)}

## Context
{cr.context}

## Task Files
{chr(10).join(f'- {f}' for f in cr.task_files)}

## Main Files
{chr(10).join(f'- {f}' for f in cr.main_files)}
"""
    atomic_write_text(outbox / "CONFLICT.md", conflict_md)

    events_path = bridge_root / "runtime" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "seq": _next_event_seq(events_path),
        "timestamp": _now_iso(),
        "type": "CONFLICT",
        "taskId": task_id,
        "conflictingFiles": cr.conflicting_files,
    }
    with open(events_path, "a") as f:
        f.write(f"{__import__('json').dumps(event)}\n")
    resolution.event_written = True

    return resolution


def _resolve_project_root(bridge_root: Path, meta: dict) -> Path | None:
    from .config import load_registry, get_project
    try:
        registry = load_registry(bridge_root / "projects.json")
        project = get_project(registry, meta.get("projectId", ""))
        if project:
            return Path(project.project_root)
    except Exception:
        pass
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_event_seq(events_path: Path) -> int:
    if not events_path.exists():
        return 1
    last = 0
    for line in events_path.read_text().splitlines():
        if line.strip():
            try:
                last = max(last, __import__("json").loads(line).get("seq", 0))
            except Exception:
                pass
    return last + 1