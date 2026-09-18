# AI生成
"""Timeout management for runtime supervisor.

Supports soft timeout (warning) and hard timeout (kill).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TimeoutConfig:
    soft_timeout_minutes: float = 0.0  # 0 = disabled
    hard_timeout_minutes: float = 0.0  # 0 = disabled
    target_minutes: float = 0.0  # Expected duration, 0 = unknown


@dataclass
class TimeoutStatus:
    elapsed_minutes: float
    soft_exceeded: bool
    hard_exceeded: bool
    soft_remaining_minutes: float
    hard_remaining_minutes: float


def check_timeout(started_at: datetime, config: TimeoutConfig) -> TimeoutStatus:
    """Check timeout status for a running task."""
    elapsed = _now() - started_at
    elapsed_min = elapsed.total_seconds() / 60.0

    soft_min = config.soft_timeout_minutes or 0.0
    hard_min = config.hard_timeout_minutes or 0.0

    soft_exceeded = soft_min > 0 and elapsed_min >= soft_min
    hard_exceeded = hard_min > 0 and elapsed_min >= hard_min

    soft_remaining = max(0.0, soft_min - elapsed_min) if soft_min > 0 else float("inf")
    hard_remaining = max(0.0, hard_min - elapsed_min) if hard_min > 0 else float("inf")

    return TimeoutStatus(
        elapsed_minutes=elapsed_min,
        soft_exceeded=soft_exceeded,
        hard_exceeded=hard_exceeded,
        soft_remaining_minutes=soft_remaining,
        hard_remaining_minutes=hard_remaining,
    )


def from_task_meta(meta: dict) -> TimeoutConfig:
    """Build TimeoutConfig from task META.json execution section."""
    execution = meta.get("execution", {})
    soft = execution.get("softTimeoutMinutes", 0)
    hard = execution.get("hardTimeoutMinutes", 0)
    target = execution.get("targetMinutes", 0)

    # Fallback to top-level timeoutMinutes for v1 compat
    if not hard:
        hard = meta.get("timeoutMinutes", 0)

    # Fallback to top-level softTimeoutMinutes/hardTimeoutMinutes for v1 compat
    if not soft:
        soft = meta.get("softTimeoutMinutes", 0)
    if not hard:
        hard = meta.get("hardTimeoutMinutes", 0)
    if not target:
        target = meta.get("targetMinutes", 0)

    return TimeoutConfig(
        soft_timeout_minutes=float(soft) if soft else 0.0,
        hard_timeout_minutes=float(hard) if hard else 0.0,
        target_minutes=float(target) if target else 0.0,
    )


def handle_soft_timeout(
    task_dir: "str | Path",
    status: TimeoutStatus,
    already_requested: bool = False,
) -> str | None:
    """Handle soft timeout action.

    Returns:
        "ASSISTANCE_REQUIRED" if checkpoint+assistance found
        "CHECKPOINT_REQUESTED" if soft timeout just triggered
        None if no action needed

    Does NOT set FAILED — soft timeout is non-destructive.
    """
    from pathlib import Path
    task_dir = Path(task_dir)

    if not status.soft_exceeded:
        return None

    outbox = task_dir / "outbox"

    # Check if worker already produced checkpoint + assistance request
    if (outbox / "CHECKPOINT.md").is_file() and (outbox / "ASSISTANCE_REQUEST.md").is_file():
        return "ASSISTANCE_REQUIRED"

    # Request checkpoint if not already done
    if not already_requested:
        checkpoint_request = task_dir / "inbox" / "CHECKPOINT_REQUEST.md"
        checkpoint_request.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_request.write_text(
            "# CHECKPOINT REQUEST\n\nSoft timeout exceeded. Please checkpoint your work.\n",
            encoding="utf-8",
        )
        return "CHECKPOINT_REQUESTED"

    return None


def handle_hard_timeout(
    task_dir: "str | Path",
    status: TimeoutStatus,
) -> bool:
    """Handle hard timeout action.

    Returns True if hard timeout exceeded (caller should force kill).
    """
    return status.hard_exceeded
