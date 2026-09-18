# AI生成
"""Bridge daemon: poll-and-dispatch loop for systemd.

Mirrors PowerShell bridge-daemon.ps1.
ExecStart: /usr/bin/python3 -m bridge.daemon run
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .atomic import atomic_write_json, atomic_write_text, read_json_or_none
from .locks import file_lock, try_file_lock
from .state import get_state, set_state, QUEUED, ACTIVE_STATES
from .dispatch import select_dispatch_plan, execute_dispatch


DAEMON_VERSION = "2.0.0"


def _bridge_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_health(state_dir: Path, status: str, extra: dict | None = None) -> None:
    health = {
        "version": DAEMON_VERSION,
        "status": status,
        "updatedAt": _now_iso(),
        "pid": os.getpid(),
    }
    if extra:
        health.update(extra)
    atomic_write_json(state_dir / "health.json", health)


def cmd_run(args) -> int:
    root = _bridge_root()
    state_dir = root / "runtime" / "daemon"
    state_dir.mkdir(parents=True, exist_ok=True)

    lock_path = state_dir / "daemon.lock"
    stop_sentinel = state_dir / "STOP_REQUESTED"
    pause_file = root / "runtime" / "PAUSE"

    # Acquire daemon lock
    if not try_file_lock(lock_path):
        print("Another daemon instance is already running.", file=sys.stderr)
        return 1

    interval = args.interval_seconds
    max_workers = args.max_workers
    backoff = args.base_backoff_seconds
    max_backoff = args.max_backoff_seconds

    write_health(state_dir, "running")

    # Signal handlers
    shutting_down = [False]

    def handle_signal(signum, frame):
        shutting_down[0] = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while not shutting_down[0]:
        # Check stop sentinel
        if stop_sentinel.exists():
            write_health(state_dir, "stopped", {"reason": "stop sentinel"})
            stop_sentinel.unlink(missing_ok=True)
            return 0

        # Check pause
        if pause_file.exists():
            write_health(state_dir, "paused")
            time.sleep(interval)
            continue

        # Dispatch
        try:
            result = execute_dispatch(root / "tasks", root, max_workers=max_workers)
            plan = result.plan

            if result.spawned:
                write_health(state_dir, "running", {
                    "dispatched": len(result.spawned),
                    "active": len(plan.active),
                    "skipped": len(plan.skipped),
                })
                backoff = args.base_backoff_seconds
            else:
                write_health(state_dir, "idle", {
                    "active": len(plan.active),
                    "skipped": len(plan.skipped),
                })

        except Exception as e:
            write_health(state_dir, "error", {"error": str(e)})
            backoff = min(backoff * 2, max_backoff)

        # Sleep
        sleep_time = interval if not plan.plan else 1
        for _ in range(sleep_time):
            if shutting_down[0] or stop_sentinel.exists():
                break
            time.sleep(1)

    write_health(state_dir, "shutdown")
    return 0


def cmd_once(args) -> int:
    """Run a single dispatch cycle."""
    root = _bridge_root()
    result = execute_dispatch(root / "tasks", root, max_workers=args.max_workers, dry_run=args.dry_run)
    plan = result.plan

    if args.dry_run:
        print(f"Active: {len(plan.active)}, Plan: {len(plan.plan)}, Skipped: {len(plan.skipped)}")
        for item in plan.plan:
            print(f"  {item.task_id} -> {item.worker_id}")
        return 0

    for tid in result.spawned:
        print(f"Dispatched {tid}")

    return 0


def cmd_status(args) -> int:
    root = _bridge_root()
    state_dir = root / "runtime" / "daemon"
    health = read_json_or_none(state_dir / "health.json")
    if not health:
        print("Daemon not running (no health.json)")
        return 1
    print(f"Daemon v{health.get('version', '?')}: {health.get('status', '?')}")
    print(f"  Updated: {health.get('updatedAt', '?')}")
    print(f"  PID: {health.get('pid', '?')}")
    if "dispatched" in health:
        print(f"  Dispatched: {health['dispatched']}")
    if "active" in health:
        print(f"  Active: {health['active']}")
    return 0


def cmd_stop(args) -> int:
    root = _bridge_root()
    state_dir = root / "runtime" / "daemon"
    state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(state_dir / "STOP_REQUESTED", "")
    print("Stop requested.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridge-daemon", description=f"Bridge Daemon v{DAEMON_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run daemon loop")
    p_run.add_argument("--interval-seconds", type=int, default=30)
    p_run.add_argument("--max-workers", type=int, default=4)
    p_run.add_argument("--base-backoff-seconds", type=int, default=2)
    p_run.add_argument("--max-backoff-seconds", type=int, default=300)

    p_once = sub.add_parser("once", help="Run single dispatch cycle")
    p_once.add_argument("--max-workers", type=int, default=4)
    p_once.add_argument("--dry-run", action="store_true")

    sub.add_parser("status", help="Show daemon status")
    sub.add_parser("stop", help="Request daemon stop")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    commands = {"run": cmd_run, "once": cmd_once, "status": cmd_status, "stop": cmd_stop}
    handler = commands.get(args.command)
    if not handler:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())