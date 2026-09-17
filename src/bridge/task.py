# AI生成
"""Task lifecycle: create tasks, read/write META.json, manage inbox/outbox.

Mirrors PowerShell task creation and instruction context functions.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, atomic_write_text, read_json
from .config import assert_safe_id


def task_dir(tasks_root: str | Path, task_id: str) -> Path:
    assert_safe_id(task_id, "TaskId")
    return Path(tasks_root) / task_id


def create_task(
    tasks_root: str | Path,
    task_id: str,
    project_id: str,
    worker_id: str | None = None,
    role: str = "implement",
    task_file: str | None = None,
    baseline: str | None = None,
    target_minutes: int = 10,
    soft_timeout_minutes: int = 12,
    timeout_minutes: int = 15,
    workspace_mode: str | None = None,
    depends_on: list[str] | None = None,
    task_kind: str = "implementation",
    parent_task_id: str | None = None,
) -> Path:
    """Create a task directory with META.json and inbox."""
    assert_safe_id(task_id, "TaskId")
    assert_safe_id(project_id, "ProjectId")

    tdir = task_dir(tasks_root, task_id)
    if tdir.exists():
        raise ValueError(f"Task directory already exists: {tdir}")

    # Create structure
    (tdir / "inbox").mkdir(parents=True)
    (tdir / "outbox").mkdir()
    (tdir / "evidence").mkdir()

    # Write META.json
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "taskId": task_id,
        "projectId": project_id,
        "role": role,
        "taskKind": task_kind,
        "targetMinutes": target_minutes,
        "softTimeoutMinutes": soft_timeout_minutes,
        "hardTimeoutMinutes": timeout_minutes,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if worker_id:
        meta["workerId"] = worker_id
    if baseline:
        meta["baseline"] = baseline
    if workspace_mode:
        meta["workspaceMode"] = workspace_mode
    if depends_on:
        meta["dependsOn"] = depends_on
    if parent_task_id:
        meta["parentTaskId"] = parent_task_id

    atomic_write_json(tdir / "META.json", meta)

    # Copy task file to inbox
    if task_file:
        src = Path(task_file)
        if not src.is_file():
            raise ValueError(f"Task file not found: {task_file}")
        shutil.copy2(src, tdir / "inbox" / "001-TASK.md")
    else:
        atomic_write_text(tdir / "inbox" / "001-TASK.md", "# TASK\n\n(No task file provided)\n")

    return tdir


def get_meta(task_directory: str | Path) -> dict[str, Any]:
    return read_json(Path(task_directory) / "META.json")


def get_instruction_context(task_directory: str | Path) -> list[str]:
    """Get sorted list of instruction file paths from inbox."""
    inbox = Path(task_directory) / "inbox"
    files = sorted(inbox.glob("*.md"))
    if not files:
        raise ValueError("No instruction files in task inbox")
    return [str(f) for f in files]


def get_latest_instruction(task_directory: str | Path) -> str:
    instructions = get_instruction_context(task_directory)
    return instructions[-1]


def archive_previous_outbox(task_directory: str | Path, attempt: int) -> None:
    """Move outbox files to evidence/attempt-NNN."""
    outbox = Path(task_directory) / "outbox"
    files = list(outbox.iterdir()) if outbox.exists() else []
    if not files:
        return
    archive = Path(task_directory) / "evidence" / f"attempt-{attempt - 1:03d}"
    archive.mkdir(parents=True, exist_ok=True)
    for f in files:
        if f.is_file():
            shutil.move(str(f), str(archive / f.name))


def write_review_pass(task_directory: str | Path, attempt: int) -> None:
    """Write a PASS instruction to inbox."""
    inbox = Path(task_directory) / "inbox"
    seq = len(list(inbox.glob("*.md"))) + 1
    atomic_write_text(
        inbox / f"{seq:03d}-PASS.md",
        f"# PASS\n\nReview passed at attempt {attempt}.\n",
    )


def write_review_fix(task_directory: str | Path, fix_content: str, attempt: int) -> None:
    """Write a FIX instruction to inbox."""
    inbox = Path(task_directory) / "inbox"
    seq = len(list(inbox.glob("*.md"))) + 1
    atomic_write_text(inbox / f"{seq:03d}-FIX.md", fix_content)


def read_outbox_summary(task_directory: str | Path) -> dict[str, str | None]:
    """Read RESULT.md, DIFF.stat, TESTS.md from outbox."""
    outbox = Path(task_directory) / "outbox"
    result = {}
    for name in ("RESULT.md", "DIFF.stat", "TESTS.md", "DIFF.patch", "BLOCKER.md"):
        p = outbox / name
        result[name] = p.read_text(encoding="utf-8") if p.is_file() else None
    return result