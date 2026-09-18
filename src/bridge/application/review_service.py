# AI生成
"""Review service: independent review workflow.

Handles the review phase of the task lifecycle:
- Review pass: mark task as approved, trigger integration
- Review fix: send fix instructions back to worker
- Independent review: ensure reviewer != implementer (anti-affinity)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..atomic import atomic_write_text, read_json_or_none, atomic_write_json
from ..core.state import (
    get_state, set_state,
    CREATED, REVIEW_REQUIRED, APPROVED, FIX_REQUIRED, DONE, FAILED,
    is_valid_transition,
)
from ..core.errors import StateTransitionError

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    task_id: str
    success: bool
    new_state: str = ""
    error: str = ""


def review_pass(
    bridge_root: Path,
    task_id: str,
    reviewer_id: str = "",
    comment: str = "",
) -> ReviewResult:
    """Mark a task as review-passed (approved).

    State transition: REVIEW_REQUIRED → APPROVED
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    current = get_state(task_dir).get("state", CREATED)

    if current != REVIEW_REQUIRED:
        return ReviewResult(
            task_id=task_id, success=False,
            error=f"Cannot review-pass from state {current}",
        )

    # Write review record
    outbox = task_dir / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)

    review_record = {
        "taskId": task_id,
        "reviewerId": reviewer_id,
        "decision": "pass",
        "comment": comment,
    }
    atomic_write_json(outbox / "REVIEW.json", review_record)

    # Transition state
    set_state(task_dir, APPROVED)

    return ReviewResult(
        task_id=task_id, success=True,
        new_state=APPROVED,
    )


def review_fix(
    bridge_root: Path,
    task_id: str,
    fix_file: str = "",
    reviewer_id: str = "",
    comment: str = "",
    fix_content: str | None = None,
) -> ReviewResult:
    """Mark a task as needing fixes.

    State transition: REVIEW_REQUIRED → FIX_REQUIRED
    Writes fix instructions to the task inbox.
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    current = get_state(task_dir).get("state", CREATED)

    if current != REVIEW_REQUIRED:
        return ReviewResult(
            task_id=task_id, success=False,
            error=f"Cannot review-fix from state {current}",
        )

    # Read fix instructions, or accept generated content directly.
    if fix_content is None:
        fix_path = Path(fix_file)
        if not fix_path.is_file():
            return ReviewResult(
                task_id=task_id, success=False,
                error=f"Fix file not found: {fix_file}",
            )
        fix_content = fix_path.read_text(encoding="utf-8")

    # Write fix instructions to inbox
    inbox = task_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    existing_fixes = sorted(inbox.glob("*-FIX.md"))
    next_num = len(existing_fixes) + 1
    fix_filename = f"{next_num:03d}-FIX.md"
    atomic_write_text(inbox / fix_filename, fix_content)

    # Write review record
    outbox = task_dir / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    review_record = {
        "taskId": task_id,
        "reviewerId": reviewer_id,
        "decision": "fix",
        "comment": comment,
        "fixFile": fix_filename,
    }
    atomic_write_json(outbox / "REVIEW.json", review_record)

    # Transition state
    set_state(task_dir, FIX_REQUIRED)

    return ReviewResult(
        task_id=task_id, success=True,
        new_state=FIX_REQUIRED,
    )


def complete_task(
    bridge_root: Path,
    task_id: str,
) -> ReviewResult:
    """Mark an approved task as fully done after integration.

    State transition: APPROVED → DONE (or INTEGRATED → DONE)
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    current = get_state(task_dir).get("state", CREATED)

    if current not in (APPROVED, "INTEGRATED"):
        return ReviewResult(
            task_id=task_id, success=False,
            error=f"Cannot complete from state {current}",
        )

    if current == APPROVED:
        set_state(task_dir, "INTEGRATING")
        set_state(task_dir, "INTEGRATED")
    set_state(task_dir, DONE)

    return ReviewResult(
        task_id=task_id, success=True,
        new_state=DONE,
    )


def check_review_independence(
    implementer_worker_id: str,
    reviewer_worker_id: str,
) -> bool:
    """Verify that reviewer is not the same as implementer.

    Returns True if independent (different workers).
    """
    return implementer_worker_id != reviewer_worker_id
