# AI生成
"""Progress display: show-progress and watch-tasks.

Mirrors PowerShell show-progress.ps1 and watch-tasks.ps1.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path

from .atomic import read_json_or_none
from .state import get_state


def _bridge_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _format_elapsed(updated_at: str | None) -> str:
    if not updated_at:
        return "-"
    try:
        dt = datetime.fromisoformat(updated_at)
        elapsed = datetime.now(timezone.utc) - dt
        if elapsed < timedelta(minutes=1):
            return f"{int(elapsed.total_seconds())}s"
        elif elapsed < timedelta(hours=1):
            return f"{int(elapsed.total_seconds() / 60)}m"
        else:
            return f"{elapsed.total_seconds() / 3600:.1f}h"
    except (ValueError, TypeError):
        return "-"


def show_progress_main() -> int:
    """Show current task progress for all active tasks."""
    root = _bridge_root()
    tasks_root = root / "tasks"

    if not tasks_root.is_dir():
        print("No tasks directory.")
        return 1

    active = []
    for d in sorted(tasks_root.iterdir()):
        if not d.is_dir():
            continue
        state = get_state(d)
        meta = read_json_or_none(d / "META.json")
        if not state or not meta:
            continue
        status = state.get("status", "")
        if status in ("QUEUED", "STARTING", "RUNNING", "REVIEW_REQUIRED"):
            active.append((d, state, meta))

    if not active:
        print("No active tasks.")
        return 0

    print(f"{'TaskID':<30} {'Status':<20} {'Worker':<15} {'Attempt':>7} {'Elapsed':>8} {'Heartbeat':<30}")
    print("-" * 115)
    for d, state, meta in active:
        task_id = state.get("taskId", d.name)
        status = state.get("status", "?")
        worker = meta.get("workerId", "-")
        attempt = state.get("attempt", 0)
        elapsed = _format_elapsed(state.get("updatedAt"))
        heartbeat = state.get("heartbeatSummary", "")[:30]
        print(f"{task_id:<30} {status:<20} {worker:<15} {attempt:>7} {elapsed:>8} {heartbeat:<30}")

    return 0


def watch_tasks_main() -> int:
    """Watch tasks with periodic refresh."""
    parser = argparse.ArgumentParser(prog="watch-tasks", description="Watch bridge tasks")
    parser.add_argument("--interval", type=int, default=5, help="Refresh interval in seconds")
    parser.add_argument("--once", action="store_true", help="Show once and exit")
    args = parser.parse_args()

    while True:
        # Clear screen
        if not args.once:
            print("\033[2J\033[H", end="")

        show_progress_main()

        # Show daemon health
        root = _bridge_root()
        health = read_json_or_none(root / "runtime" / "daemon" / "health.json")
        if health:
            print(f"\nDaemon: {health.get('status', '?')} (updated {health.get('updatedAt', '?')})")

        if args.once:
            return 0

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(watch_tasks_main())