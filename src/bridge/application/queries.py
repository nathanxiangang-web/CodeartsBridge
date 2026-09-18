# AI生成
"""QueryService — read-only queries for dashboard and CLI.

Phase 8: Application Layer service for queries.
"""
from __future__ import annotations

import json
from pathlib import Path


def get_dashboard_summary(bridge_root: str | Path) -> dict:
    """Get dashboard summary: task counts by state, worker counts, recent events."""
    bridge_root = Path(bridge_root)
    tasks_dir = bridge_root / "tasks"

    state_counts: dict[str, int] = {}
    if tasks_dir.exists():
        for d in tasks_dir.iterdir():
            if not d.is_dir():
                continue
            sf = d / "state.json"
            if sf.exists():
                try:
                    s = json.loads(sf.read_text(encoding="utf-8")).get("state", "UNKNOWN")
                    state_counts[s] = state_counts.get(s, 0) + 1
                except Exception:
                    pass

    from bridge.application.workers import list_workers
    workers = list_workers(bridge_root)
    worker_summary = {
        "total": len(workers),
        "enabled": sum(1 for w in workers if w.get("enabled", True)),
        "disabled": sum(1 for w in workers if not w.get("enabled", True)),
    }

    from bridge.application.projects import list_projects
    projects = list_projects(bridge_root)

    return {
        "tasks": state_counts,
        "workers": worker_summary,
        "projects": len(projects),
        "total_tasks": sum(state_counts.values()),
    }


def get_recent_events(bridge_root: str | Path, limit: int = 20) -> list[dict]:
    """Get recent events from the event store."""
    from bridge.core.events import EventStore
    store = EventStore(bridge_root / "events")
    events = store.recent(limit)
    return [
        {
            "eventId": e.event_id,
            "type": e.type,
            "taskId": e.task_id,
            "timestamp": e.timestamp,
            "payload": e.payload,
        }
        for e in events
    ]


def get_task_assignments(bridge_root: str | Path, task_id: str) -> list[dict]:
    """Get all scheduler assignments for a task."""
    from bridge.application.assignments import list_assignments

    return [
        assignment
        for assignment in list_assignments(bridge_root)
        if assignment.get("taskId") == task_id
    ]


def get_worker_assignments(bridge_root: str | Path, worker_id: str) -> list[dict]:
    """Get all scheduler assignments for a worker."""
    from bridge.application.assignments import list_assignments

    return [
        assignment
        for assignment in list_assignments(bridge_root)
        if assignment.get("workerId") == worker_id
    ]