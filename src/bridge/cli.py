# AI生成
"""CLI entry point for the bridge.

Usage:
    python -m bridge.cli bootstrap
    python -m bridge.cli doctor
    python -m bridge.cli status
    python -m bridge.cli create -p <project> -w <worker> --role implement -t <task-id> --task-file <file>
    python -m bridge.cli dispatch --max-workers 4
    python -m bridge.cli run -t <task-id>
    python -m bridge.cli review-pass -t <task-id>
    python -m bridge.cli review-fix -t <task-id> --fix-file <file>
    python -m bridge.cli cancel -t <task-id>
    python -m bridge.cli pause
    python -m bridge.cli resume
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
from pathlib import Path

from . import __version__
from .atomic import atomic_write_text, read_json_or_none
from .config import load_registry, load_workers_registry, get_project, get_worker
from .state import get_state, set_state, READY, QUEUED, DONE, REVIEW_REQUIRED, FIX_REQUIRED
from .task import create_task, write_review_pass, write_review_fix, read_outbox_summary
from .dispatch import select_dispatch_plan, execute_dispatch
from .auto_dispatch import auto_dispatch, AutoDispatchResult
from .integration import integrate_task, integrate_loop, IntegrationResult
from .worker import run_worker
from .codearts import find_codearts_cli, REQUIRED_MODEL

# v2 Application Service imports
from .application.task_service import create_task as v2_create_task, cancel_task as v2_cancel_task, list_tasks as v2_list_tasks
from .application.review_service import review_pass as v2_review_pass, review_fix as v2_review_fix
from .application.projects import list_projects as v2_list_projects
from .application.workers import list_workers as v2_list_workers
from .application.queries import get_dashboard_summary as v2_dashboard_summary


def _bridge_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _ensure_layout(root: Path) -> None:
    for d in ("tasks", "runtime", "runtime/locks", "runtime/leases",
              "runtime/worktrees", "runtime/logs", "runtime/logs/dispatcher",
              "archive", "work"):
        (root / d).mkdir(parents=True, exist_ok=True)


def cmd_bootstrap(args) -> int:
    root = _bridge_root()
    _ensure_layout(root)
    print(f"Bridge layout initialized at {root}")
    return 0


def cmd_doctor(args) -> int:
    root = _bridge_root()
    print(f"Bridge v{__version__}")
    print(f"Root: {root}")

    # Check projects.json
    projects_path = root / "projects.json"
    if projects_path.is_file():
        reg = load_registry(projects_path)
        print(f"Projects: {len(reg.projects)} registered")
    else:
        print("Projects: MISSING projects.json")

    # Check workers.json
    workers_path = root / "workers.json"
    if workers_path.is_file():
        wr = load_workers_registry(workers_path)
        print(f"Workers: {len(wr.workers)} registered")
        for w in wr.workers:
            print(f"  {w.id}: enabled={w.enabled}, caps={w.capabilities}")
    else:
        print("Workers: MISSING workers.json")

    # Check CLI
    cli = find_codearts_cli()
    print(f"CodeArts CLI: {cli or 'NOT FOUND'}")
    print(f"Model: {REQUIRED_MODEL}")

    # Check SSH
    ssh = shutil.which("ssh")
    print(f"SSH: {ssh or 'NOT FOUND'}")
    scp = shutil.which("scp")
    print(f"SCP: {scp or 'NOT FOUND'}")

    return 0


def cmd_status(args) -> int:
    root = _bridge_root()
    tasks_root = root / "tasks"

    if not tasks_root.is_dir():
        print("No tasks directory. Run 'bootstrap' first.")
        return 1

    tasks = []
    for d in sorted(tasks_root.iterdir()):
        if not d.is_dir():
            continue
        state = get_state(d)
        meta = read_json_or_none(d / "META.json")
        if not state or not meta:
            continue
        tasks.append({
            "taskId": state.get("taskId", d.name),
            "status": state.get("status", "?"),
            "project": meta.get("projectId", "?"),
            "worker": meta.get("workerId", "-"),
            "role": meta.get("role", "-"),
            "attempt": state.get("attempt", 0),
        })

    if not tasks:
        print("No tasks.")
        return 0

    print(f"{'TaskID':<30} {'Status':<20} {'Project':<25} {'Worker':<15} {'Role':<10} {'Attempt':>7}")
    print("-" * 110)
    for t in tasks:
        print(f"{t['taskId']:<30} {t['status']:<20} {t['project']:<25} {t['worker']:<15} {t['role']:<10} {t['attempt']:>7}")

    return 0


def cmd_create(args) -> int:
    root = _bridge_root()
    _ensure_layout(root)

    # Use v2 Application Service instead of direct file operations
    v2_create_task(
        bridge_root=root,
        project_id=args.project_id,
        worker_id=args.worker_id,
        role=args.role,
        task_id=args.task_id,
        task_file=args.task_file or "",
        required_skills=[],
        depends_on=args.depends_on or [],
    )
    print(f"Task {args.task_id} created via TaskService")
    return 0


def cmd_dispatch(args) -> int:
    root = _bridge_root()
    tasks_root = root / "tasks"

    result = execute_dispatch(
        tasks_root, root,
        max_workers=args.max_workers,
        dry_run=args.dry_run,
    )
    plan = result.plan

    if args.dry_run:
        print("=== Dry Run ===")
        print(f"Active: {len(plan.active)}")
        for a in plan.active:
            print(f"  {a['taskId']}: {a['status']}")
        print(f"\nPlan: {len(plan.plan)}")
        for item in plan.plan:
            print(f"  {item.task_id} -> worker={item.worker_id}, mode={item.workspace_mode}")
        print(f"\nSkipped: {len(plan.skipped)}")
        for s in plan.skipped:
            print(f"  {s.task_id}: {s.reason}")
        return 0

    if not plan.plan:
        print("No tasks to dispatch.")
        if plan.skipped:
            print("\nSkipped:")
            for s in plan.skipped:
                print(f"  {s.task_id}: {s.reason}")
        return 0

    print(f"Dispatched {len(result.spawned)} task(s):")
    for tid in result.spawned:
        print(f"  {tid} spawned")

    if result.failed:
        print(f"\nFailed {len(result.failed)}:")
        for tid, err in result.failed:
            print(f"  {tid}: {err}")

    if plan.skipped:
        print(f"\nSkipped {len(plan.skipped)}:")
        for s in plan.skipped:
            print(f"  {s.task_id}: {s.reason}")

    return 0


def cmd_auto_dispatch(args) -> int:
    """Auto-dispatch ready tasks to available workers."""
    root = _bridge_root()
    _ensure_layout(root)

    def _run_once(dry_run: bool) -> AutoDispatchResult:
        result = auto_dispatch(
            bridge_root=root,
            max_workers=args.max_workers,
            dry_run=dry_run,
        )
        tag = "[dry-run] " if dry_run else ""
        print(f"{tag}planned={result.planned} dispatched={result.dispatched} skipped={result.skipped}")
        for a in result.assignments:
            tid = a["taskId"]
            wid = a["workerId"]
            rol = a["role"]
            print(f"  {tid} -> {wid} ({rol})")
        if result.skipped_details:
            for s in result.skipped_details:
                sid = s.get("taskId", "?")
                sreason = s.get("reason", "?")
                print(f"  skip {sid}: {sreason}")
        if result.errors:
            for e in result.errors:
                print(f"  ERROR: {e}")
        return result

    if args.loop:
        import time
        interval = args.interval
        print(f"Auto-dispatch loop: interval={interval}s max_workers={args.max_workers}")
        try:
            while True:
                _run_once(args.dry_run)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nAuto-dispatch loop stopped.")
            return 0
    else:
        _run_once(args.dry_run)

    return 0


def cmd_run(args) -> int:
    root = _bridge_root()
    tdir = root / "tasks" / args.task_id
    if not tdir.is_dir():
        print(f"Task not found: {args.task_id}")
        return 1

    meta = read_json_or_none(tdir / "META.json")
    if not meta:
        print(f"META.json missing for task {args.task_id}")
        return 1

    registry = load_registry(root / "projects.json")
    project = get_project(registry, meta["projectId"])

    worker = None
    state_data = get_state(tdir)
    worker_id = meta.get("workerId") or state_data.get("assignedWorkerId")
    if worker_id:
        workers_path = root / "workers.json"
        if workers_path.is_file():
            wr = load_workers_registry(workers_path)
            worker = get_worker(wr, worker_id)

    state = run_worker(tdir, project, worker, root, quiet=args.quiet)
    print(f"Task {args.task_id}: {state.get('status')} - {state.get('message', '')}")
    return 0


def cmd_review_pass(args) -> int:
    root = _bridge_root()
    # Use v2 Application Service
    result = v2_review_pass(root, args.task_id, reviewer_id="cli")
    if result.success:
        print(f"Task {args.task_id}: {result.new_state}")
        return 0
    print(f"Task {args.task_id}: FAILED - {result.error}")
    return 1


def cmd_review_fix(args) -> int:
    root = _bridge_root()
    fix_file = args.fix_file or ""
    if not fix_file:
        # Write a default fix file
        fix_path = root / "tasks" / args.task_id / "inbox" / "REVIEW_FIX.md"
        fix_path.parent.mkdir(parents=True, exist_ok=True)
        fix_path.write_text("# FIX\n\nPlease fix the issues.\n", encoding="utf-8")
        fix_file = str(fix_path)
    # Use v2 Application Service
    result = v2_review_fix(root, args.task_id, fix_file, reviewer_id="cli")
    if result.success:
        print(f"Task {args.task_id}: {result.new_state}")
        return 0
    print(f"Task {args.task_id}: FAILED - {result.error}")
    return 1


def cmd_cancel(args) -> int:
    root = _bridge_root()
    # Use v2 Application Service
    result = v2_cancel_task(root, args.task_id, "cancelled by CLI")
    print(f"Task {args.task_id}: {result.get('state', 'CANCELLED')}")
    return 0


def cmd_pause(args) -> int:
    root = _bridge_root()
    atomic_write_text(root / "runtime" / "PAUSE", "")
    print("Dispatch paused.")
    return 0


def cmd_resume(args) -> int:
    root = _bridge_root()
    pause_file = root / "runtime" / "PAUSE"
    if pause_file.exists():
        pause_file.unlink()
    print("Dispatch resumed.")
    return 0


def cmd_serve(args) -> int:
    """Start unified bridge server (Phase 12: bridge serve).

    Starts: HTTP API + Web UI + MCP + Health Service.
    """
    import signal
    import time
    from .api.server import BridgeAPIServer

    root = _bridge_root()
    _ensure_layout(root)

    # Start HTTP API server (serves Web UI + REST API + SSE)
    api_server = BridgeAPIServer(bridge_root=root, host=args.host, port=args.port)
    api_server.start()
    print(f"Bridge serve started:")
    print(f"  Web UI:  http://{args.host}:{args.port}")
    print(f"  API:     http://{args.host}:{args.port}/api")
    print(f"  Health:  http://{args.host}:{args.port}/api/health")
    print(f"  Events:  http://{args.host}:{args.port}/api/events (SSE)")

    # Start MCP server (stdio mode, in separate thread)
    mcp_thread = None
    if not args.no_mcp:
        from .interfaces.mcp.server import MCPServer
        mcp_server = MCPServer(bridge_root=root)

        def _run_mcp():
            try:
                mcp_server.start()
            except Exception:
                pass  # MCP stdio may not be available in all contexts

        mcp_thread = threading.Thread(target=_run_mcp, daemon=True)
        mcp_thread.start()
        print(f"  MCP:     stdio (JSON-RPC 2.0)")

    print(f"\nPress Ctrl+C to stop.")

    def _shutdown(*_):
        api_server.stop()
        if mcp_thread:
            mcp_thread.join(timeout=2)
        print("\nBridge stopped.")

    try:
        try:
            signal.signal(signal.SIGINT, _shutdown)
            signal.signal(signal.SIGTERM, _shutdown)
        except ValueError:
            pass  # signal only works in main thread
        while api_server.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        _shutdown()
    return 0


def cmd_integrate(args) -> int:
    """Integrate DONE-state tasks into the main branch via cherry-pick."""
    root = _bridge_root()
    _ensure_layout(root)

    if args.task_id:
        result = integrate_task(
            args.task_id, root,
            dry_run=args.dry_run,
        )
        tag = "[dry-run] " if args.dry_run else ""
        if result.success:
            if args.dry_run:
                print(f"{tag}{result.task_id}: would cherry-pick {result.commit_sha[:12]}")
            else:
                print(f"{result.task_id}: integrated -> {result.merged_sha[:12]}")
                print(f"  baseline_updated={result.baseline_updated} tests_passed={result.verification_passed}")
        else:
            print(f"{result.task_id}: FAILED - {result.error}")
            if result.conflict_files:
                print(f"  conflicts: {result.conflict_files}")
        return 0 if result.success else 1

    results = integrate_loop(root, dry_run=args.dry_run)

    if not results:
        print("No DONE tasks pending integration.")
        return 0

    tag = "[dry-run] " if args.dry_run else ""
    succeeded = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    print(f"{tag}integrated={succeeded} failed={failed} total={len(results)}")
    for r in results:
        if r.success:
            if args.dry_run:
                print(f"  {r.task_id}: would cherry-pick {r.commit_sha[:12]}")
            else:
                print(f"  {r.task_id}: -> {r.merged_sha[:12]}")
        else:
            print(f"  {r.task_id}: FAILED - {r.error}")
    return 0 if failed == 0 else 1


def cmd_projects(args) -> int:
    """List registered projects via ProjectService."""
    root = _bridge_root()
    projects = v2_list_projects(root)
    if not projects:
        print("No projects registered.")
        return 0
    for p in projects:
        print(f"  {p.get('projectId', p.get('id', '?'))}: {p.get('name', '')}")
    return 0


def cmd_workers(args) -> int:
    """List registered workers via WorkerService."""
    root = _bridge_root()
    workers = v2_list_workers(root)
    if not workers:
        print("No workers registered.")
        return 0
    for w in workers:
        print(f"  {w.get('id', '?')}: roles={w.get('roles', [])}, enabled={w.get('enabled', True)}")
    return 0


def cmd_telemetry(args) -> int:
    """Show telemetry and statistics report."""
    from .telemetry import generate_report_text
    root = _bridge_root()
    tasks_dir = root / "tasks"
    if not tasks_dir.is_dir():
        print("No tasks directory found.")
        return 1
    print(generate_report_text(tasks_dir))
    return 0



def cmd_adaptive_dispatch(args) -> int:
    """Adaptive dispatch: tune timeouts and worker bias from telemetry, then auto-dispatch."""
    from .adaptive import adaptive_dispatch
    root = _bridge_root()
    _ensure_layout(root)
    result = adaptive_dispatch(
        bridge_root=root,
        max_workers=args.max_workers,
        dry_run=args.dry_run,
    )
    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}planned={result.planned} dispatched={result.dispatched} skipped={result.skipped}")
    for a in result.assignments:
        print(f"  {a['taskId']} -> {a['workerId']} ({a['role']})")
    if result.skipped_details:
        for s in result.skipped_details:
            print(f"  skip {s.get('taskId', '?')}: {s.get('reason', '?')}")
    if result.errors:
        for e in result.errors:
            print(f"  ERROR: {e}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridge", description=f"Codex-GLM Bridge v{__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap", help="Initialize bridge directory layout")
    sub.add_parser("doctor", help="Check environment and configuration")
    sub.add_parser("status", help="Show all projects and tasks")

    p_create = sub.add_parser("create", help="Create a new task")
    p_create.add_argument("-p", "--project-id", required=True)
    p_create.add_argument("-w", "--worker-id", default=None)
    p_create.add_argument("--role", default="implement", choices=["architect", "implement", "review", "test"])
    p_create.add_argument("-t", "--task-id", required=True)
    p_create.add_argument("--task-file", default=None)
    p_create.add_argument("--baseline", default=None)
    p_create.add_argument("--target-minutes", type=int, default=10)
    p_create.add_argument("--soft-timeout-minutes", type=int, default=12)
    p_create.add_argument("--timeout-minutes", type=int, default=15)
    p_create.add_argument("--workspace-mode", default=None, choices=["shared-readonly", "worktree", "existing"])
    p_create.add_argument("--depends-on", nargs="*", default=None)

    p_dispatch = sub.add_parser("dispatch", help="Dispatch tasks to workers")
    p_dispatch.add_argument("--max-workers", type=int, default=4)
    p_dispatch.add_argument("--dry-run", action="store_true")

    p_auto = sub.add_parser("auto-dispatch", help="Auto-dispatch ready tasks to workers")
    p_auto.add_argument("--loop", action="store_true", help="Run continuously until Ctrl-C")
    p_auto.add_argument("--interval", type=int, default=10, help="Loop interval in seconds")
    p_auto.add_argument("--max-workers", type=int, default=4)
    p_auto.add_argument("--dry-run", action="store_true", help="Show plan without dispatching")

    p_run = sub.add_parser("run", help="Run a single task")
    p_run.add_argument("-t", "--task-id", required=True)
    p_run.add_argument("--quiet", action="store_true")

    p_rp = sub.add_parser("review-pass", help="Mark task as passed")
    p_rp.add_argument("-t", "--task-id", required=True)

    p_rf = sub.add_parser("review-fix", help="Request fix for task")
    p_rf.add_argument("-t", "--task-id", required=True)
    p_rf.add_argument("--fix-file", default=None)

    p_cancel = sub.add_parser("cancel", help="Cancel a task")
    p_cancel.add_argument("-t", "--task-id", required=True)

    sub.add_parser("pause", help="Pause dispatch")
    sub.add_parser("resume", help="Resume dispatch")

    p_serve = sub.add_parser("serve", help="Start unified bridge server (API + Web UI + MCP)")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--no-mcp", action="store_true", help="Disable MCP server")

    sub.add_parser("projects", help="List registered projects")
    sub.add_parser("workers", help="List registered workers")
    sub.add_parser("telemetry", help="Show telemetry and statistics report")
    p_adaptive = sub.add_parser("adaptive-dispatch", help="Adaptive dispatch with telemetry-tuned parameters")
    p_adaptive.add_argument("--max-workers", type=int, default=4)
    p_adaptive.add_argument("--dry-run", action="store_true", help="Show plan without dispatching")


    p_integrate = sub.add_parser("integrate", help="Integrate DONE tasks into main branch")
    p_integrate.add_argument("--task-id", default=None, help="Integrate specific task")
    p_integrate.add_argument("--loop", action="store_true", help="Continuously integrate all DONE tasks")
    p_integrate.add_argument("--dry-run", action="store_true", help="Show plan without merging")

    p_pipeline = sub.add_parser("pipeline", help="Run full pipeline: plan->dispatch->review->integrate")
    p_pipeline.add_argument("--config", default=None, help="Config file path")
    p_pipeline.add_argument("--dry-run", action="store_true", help="Show what each step would do")
    p_pipeline.add_argument("--once", action="store_true", help="Run single cycle then exit")
    p_pipeline.add_argument("--interval", type=float, default=10.0, help="Idle interval in seconds")
    p_pipeline.add_argument("--max-workers", type=int, default=4)

    p_cost = sub.add_parser("cost", help="Show cost tracking report")
    p_cost.add_argument("--project", default=None, help="Filter by project ID")
    p_cost.add_argument("--summary", action="store_true", help="Summary only")
    return parser


def cmd_cost(args) -> int:
    from bridge.cost import format_cost_report
    root = _bridge_root()
    print(format_cost_report(root))
    return 0


def cmd_pipeline(args) -> int:
    from bridge.pipeline import run_pipeline, PipelineConfig
    root = _bridge_root()
    config = PipelineConfig(
        interval=args.interval,
        max_workers=args.max_workers,
        dry_run=args.dry_run,
        once=args.once,
    )
    run_pipeline(root, config)
    return 0


COMMAND_MAP = {
    "bootstrap": cmd_bootstrap,
    "doctor": cmd_doctor,
    "status": cmd_status,
    "create": cmd_create,
    "dispatch": cmd_dispatch,
    "auto-dispatch": cmd_auto_dispatch,
    "run": cmd_run,
    "review-pass": cmd_review_pass,
    "review-fix": cmd_review_fix,
    "cancel": cmd_cancel,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "serve": cmd_serve,
    "projects": cmd_projects,
    "workers": cmd_workers,
    "telemetry": cmd_telemetry,
    "adaptive-dispatch": cmd_adaptive_dispatch,
    "integrate": cmd_integrate,
    "pipeline": cmd_pipeline,
    "cost": cmd_cost,
}


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handler = COMMAND_MAP.get(args.command)
    if not handler:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())