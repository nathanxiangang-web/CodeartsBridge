# AI生成
"""Pipeline orchestrator: ties auto-dispatch, architect loop, integration,
and conflict resolution into a single continuous pipeline.

`bridge pipeline` runs the full loop autonomously:
  plan -> dispatch -> worker-execute -> review -> integrate -> resolve -> repeat
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .atomic import atomic_write_json, read_json_or_none
from .auto_dispatch import auto_dispatch, AutoDispatchResult
from .architect_loop import architect_loop, ArchitectResult
from .integration import integrate_loop, IntegrationResult
from .conflict import detect_conflict, handle_conflict, ConflictResult


@dataclass
class CycleResult:
    """Summary of one pipeline cycle."""
    cycle: int = 0
    dispatched: int = 0
    reviewed: int = 0
    integrated: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)
    cycle_time: float = 0.0


@dataclass
class PipelineState:
    """Persisted pipeline state, recoverable on restart."""
    cycle_count: int = 0
    status: str = "IDLE"  # RUNNING, IDLE, STOPPED, BLOCKED
    last_cycle_time: float = 0.0
    total_dispatched: int = 0
    total_reviewed: int = 0
    total_integrated: int = 0
    total_conflicts: int = 0
    first_pass_count: int = 0
    total_pass_count: int = 0

    def to_dict(self) -> dict:
        return {
            "cycleCount": self.cycle_count,
            "status": self.status,
            "lastCycleTime": self.last_cycle_time,
            "totalDispatched": self.total_dispatched,
            "totalReviewed": self.total_reviewed,
            "totalIntegrated": self.total_integrated,
            "totalConflicts": self.total_conflicts,
            "firstPassCount": self.first_pass_count,
            "totalPassCount": self.total_pass_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineState":
        return cls(
            cycle_count=d.get("cycleCount", 0),
            status=d.get("status", "IDLE"),
            last_cycle_time=d.get("lastCycleTime", 0.0),
            total_dispatched=d.get("totalDispatched", 0),
            total_reviewed=d.get("totalReviewed", 0),
            total_integrated=d.get("totalIntegrated", 0),
            total_conflicts=d.get("totalConflicts", 0),
            first_pass_count=d.get("firstPassCount", 0),
            total_pass_count=d.get("totalPassCount", 0),
        )


@dataclass
class PipelineConfig:
    """Configuration for the pipeline loop."""
    interval: float = 10.0
    max_workers: int = 4
    dry_run: bool = False
    once: bool = False


def _load_state(bridge_root: Path) -> PipelineState:
    path = bridge_root / "runtime" / "pipeline-state.json"
    data = read_json_or_none(path)
    if data:
        return PipelineState.from_dict(data)
    return PipelineState()


def _save_state(bridge_root: Path, state: PipelineState) -> None:
    path = bridge_root / "runtime" / "pipeline-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, state.to_dict())


def _has_active_tasks(bridge_root: Path) -> bool:
    from .core.state import get_state, CANDIDATE_STATES, ACTIVE_STATES
    tasks_root = bridge_root / "tasks"
    if not tasks_root.exists():
        return False
    for task_dir in tasks_root.iterdir():
        if not task_dir.is_dir():
            continue
        status = get_state(task_dir).get("state", "")
        if status in CANDIDATE_STATES or status in ACTIVE_STATES:
            return True
    return False


def run_pipeline_cycle(bridge_root: Path, state: PipelineState, config: PipelineConfig) -> CycleResult:
    """Run one pipeline cycle: review -> dispatch -> integrate -> conflict-check.

    Returns CycleResult with counts. Updates state in place.
    """
    bridge_root = Path(bridge_root)
    start = time.time()
    result = CycleResult(cycle=state.cycle_count + 1)

    # Step 1: Architect review (review REVIEW_REQUIRED tasks)
    try:
        ar = architect_loop(bridge_root=bridge_root)
        result.reviewed = ar.reviewed
        state.total_reviewed += ar.reviewed
        state.first_pass_count += ar.passed
        state.total_pass_count += ar.passed
        if ar.errors:
            result.errors.extend(ar.errors)
    except Exception as e:
        result.errors.append(f"architect_loop: {e}")

    # Step 2: Auto-dispatch (dispatch READY tasks)
    try:
        dr = auto_dispatch(bridge_root=bridge_root, max_workers=config.max_workers, dry_run=config.dry_run)
        result.dispatched = dr.dispatched
        state.total_dispatched += dr.dispatched
        if dr.errors:
            result.errors.extend(dr.errors)
    except Exception as e:
        result.errors.append(f"auto_dispatch: {e}")

    # Step 3: Integrate APPROVED tasks
    try:
        results = integrate_loop(bridge_root, dry_run=config.dry_run)
        successful = [r for r in results if r.success and not r.dry_run]
        result.integrated = len(successful)
        state.total_integrated += len(successful)
        for r in results:
            if not r.success:
                result.errors.append(
                    f"integration {r.task_id}: {r.error or 'unknown failure'}"
                )
    except Exception as e:
        result.errors.append(f"integrate_loop: {e}")

    # Step 4: Record integration conflicts already identified by the engine.
    try:
        from .core.state import get_state, CONFLICT
        tasks_root = bridge_root / "tasks"
        if tasks_root.exists():
            for task_dir in tasks_root.iterdir():
                if not task_dir.is_dir():
                    continue
                if get_state(task_dir).get("state") == CONFLICT:
                    result.conflicts += 1
                    state.total_conflicts += 1
    except Exception as e:
        result.errors.append(f"conflict_check: {e}")

    result.cycle_time = time.time() - start
    state.cycle_count += 1
    state.last_cycle_time = result.cycle_time

    if result.errors and not result.dispatched and not result.reviewed and not result.integrated:
        state.status = "BLOCKED"
    elif not _has_active_tasks(bridge_root):
        state.status = "IDLE"
    else:
        state.status = "RUNNING"

    return result


def run_pipeline(bridge_root: Path, config: PipelineConfig | None = None) -> None:
    """Run the pipeline continuously until STOPPED/BLOCKED or --once.

    Persists state between cycles. Idles (sleeps) when no active tasks.
    """
    bridge_root = Path(bridge_root)
    config = config or PipelineConfig()
    state = _load_state(bridge_root)

    if config.once:
        result = run_pipeline_cycle(bridge_root, state, config)
        _save_state(bridge_root, state)
        print(f"Cycle {result.cycle}: dispatched={result.dispatched} "
              f"reviewed={result.reviewed} integrated={result.integrated} "
              f"conflicts={result.conflicts} time={result.cycle_time:.1f}s")
        if result.errors:
            for e in result.errors:
                print(f"  ERROR: {e}")
        return

    print(f"Pipeline started (interval={config.interval}s, max_workers={config.max_workers})")
    try:
        while True:
            result = run_pipeline_cycle(bridge_root, state, config)
            _save_state(bridge_root, state)

            print(f"Cycle {result.cycle}: dispatched={result.dispatched} "
                  f"reviewed={result.reviewed} integrated={result.integrated} "
                  f"conflicts={result.conflicts} time={result.cycle_time:.1f}s")
            if result.errors:
                for e in result.errors:
                    print(f"  ERROR: {e}")

            if state.status == "BLOCKED":
                print("Pipeline BLOCKED — stopping")
                break

            if state.status == "IDLE":
                time.sleep(config.interval)
            else:
                time.sleep(max(1.0, config.interval / 2))
    except KeyboardInterrupt:
        state.status = "STOPPED"
        _save_state(bridge_root, state)
        print("Pipeline stopped by user")