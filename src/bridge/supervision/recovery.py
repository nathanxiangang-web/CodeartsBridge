"""Recovery utilities for the supervision subsystem."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from bridge.supervision.model import (
    SUPERVISION_OFFSETS_SECONDS,
    SupervisionPlan,
)


def _plan_from_dict(data: dict) -> SupervisionPlan:
    return SupervisionPlan(
        task_id=data["taskId"],
        worker_id=data.get("workerId"),
        running_at=data["runningAt"],
        next_stage=data.get("nextStage", 0),
        next_due_at=data.get("nextDueAt"),
        completed_stages=data.get("completedStages", []),
        cancelled=data.get("cancelled", False),
        last_event_id=data.get("lastEventId"),
        last_event_at=data.get("lastEventAt"),
        last_progress_hash=data.get("lastProgressHash"),
        no_progress_count=data.get("noProgressCount", 0),
        repeated_error_count=data.get("repeatedErrorCount", 0),
        version=data.get("version", 1),
    )


def recover_plans(bridge_root: Path) -> list[SupervisionPlan]:
    """Read all supervision plans from disk."""
    plans_dir = Path(bridge_root) / "runtime" / "supervision" / "tasks"
    if not plans_dir.exists():
        return []
    plans: list[SupervisionPlan] = []
    for path in sorted(plans_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            plans.append(_plan_from_dict(data))
        except (json.JSONDecodeError, KeyError):
            continue
    return plans


def _elapsed_seconds(running_at: str, now_wallclock: str) -> float:
    start = running_at
    if start.endswith("Z"):
        start = start[:-1] + "+00:00"
    now = now_wallclock
    if now.endswith("Z"):
        now = now[:-1] + "+00:00"
    start_dt = datetime.fromisoformat(start)
    now_dt = datetime.fromisoformat(now)
    return (now_dt - start_dt).total_seconds()


def compute_missed_stages(plan: SupervisionPlan, now_wallclock: str) -> list[int]:
    """Determine which stages should have fired but did not (due to restart).

    A stage is missed if its offset is less than the elapsed time since
    runningAt AND it is not already in completedStages.
    """
    elapsed = _elapsed_seconds(plan.running_at, now_wallclock)
    missed: list[int] = []
    for stage, offset in enumerate(SUPERVISION_OFFSETS_SECONDS):
        if offset < elapsed and stage not in plan.completed_stages:
            missed.append(stage)
    return missed
