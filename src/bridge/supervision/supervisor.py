"""Supervisor: orchestrates per-task inspections using DeadlineScheduler."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Protocol

from bridge.supervision.model import (
    ArchitectEvent,
    InspectionResult,
    SupervisionPlan,
)
from bridge.supervision.schedule import DeadlineScheduler
from bridge.supervision.policy import should_escalate, classify_completion


class Inspector(Protocol):
    """Protocol for inspecting a task at a supervision stage."""

    def inspect(
        self, task_id: str, stage: int, plan: SupervisionPlan
    ) -> InspectionResult:
        ...


class Supervisor:
    """Orchestrates per-task inspections, persists plans, supports restart recovery."""

    def __init__(
        self,
        bridge_root: Path,
        scheduler: DeadlineScheduler,
        inspector: Inspector,
    ) -> None:
        self._bridge_root = Path(bridge_root)
        self._scheduler = scheduler
        self._inspector = inspector
        self._plans: dict[str, SupervisionPlan] = {}
        self._plans_dir = self._bridge_root / "runtime" / "supervision" / "tasks"
        self._plans_dir.mkdir(parents=True, exist_ok=True)

    def _plan_path(self, task_id: str) -> Path:
        return self._plans_dir / f"{task_id}.json"

    def _persist_plan(self, plan: SupervisionPlan) -> None:
        data = {
            "taskId": plan.task_id,
            "workerId": plan.worker_id,
            "runningAt": plan.running_at,
            "nextStage": plan.next_stage,
            "nextDueAt": plan.next_due_at,
            "completedStages": plan.completed_stages,
            "cancelled": plan.cancelled,
            "lastEventId": plan.last_event_id,
            "lastEventAt": plan.last_event_at,
            "lastProgressHash": plan.last_progress_hash,
            "noProgressCount": plan.no_progress_count,
            "repeatedErrorCount": plan.repeated_error_count,
            "version": plan.version,
        }
        self._plan_path(plan.task_id).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def _load_plan(self, task_id: str) -> SupervisionPlan | None:
        path = self._plan_path(task_id)
        if not path.exists():
            return None
        return self._plan_from_dict(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
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

    def on_task_started(
        self, task_id: str, worker_id: str, running_at: str
    ) -> None:
        """Create SupervisionPlan, persist it, schedule deadlines.

        runningAt is write-once: if a plan already exists with a runningAt
        set, the existing value is preserved and only deadlines are
        rescheduled.
        """
        existing = self._load_plan(task_id)
        if existing is not None and existing.running_at:
            plan = existing
        else:
            plan = SupervisionPlan(
                task_id=task_id,
                worker_id=worker_id,
                running_at=running_at,
                next_stage=0,
                next_due_at=None,
                completed_stages=[],
            )
            self._persist_plan(plan)

        self._plans[task_id] = plan

        now_monotonic = time.monotonic()
        self._scheduler.start_task(task_id, now_monotonic, running_at)

    def on_task_completed(self, task_id: str) -> None:
        """Cancel remaining deadlines and mark plan as completed."""
        self._scheduler.cancel_task(task_id)

        plan = self._plans.get(task_id)
        if plan is None:
            plan = self._load_plan(task_id)
        if plan is not None:
            plan.cancelled = True
            self._persist_plan(plan)
            self._plans[task_id] = plan

    def tick(
        self, now_monotonic: float, now_wallclock: str
    ) -> list[ArchitectEvent]:
        """Pop due deadlines, run inspections, return events for Architect.

        Normal inspections return [] (no Architect involvement).
        Alerts return [ArchitectEvent(...)].
        """
        events: list[ArchitectEvent] = []

        for entry in self._scheduler.pop_due(now_monotonic):
            plan = self._plans.get(entry.task_id)
            if plan is None:
                plan = self._load_plan(entry.task_id)
                if plan is None:
                    continue
                self._plans[entry.task_id] = plan

            if plan.cancelled:
                continue

            if entry.stage in plan.completed_stages:
                continue

            result = self._inspector.inspect(entry.task_id, entry.stage, plan)

            plan.completed_stages.append(entry.stage)
            plan.next_stage = entry.stage + 1

            if result.progress_hash is not None:
                if plan.last_progress_hash == result.progress_hash:
                    plan.no_progress_count += 1
                else:
                    plan.no_progress_count = 0
                    plan.last_progress_hash = result.progress_hash

            if result.error_signature is not None:
                plan.repeated_error_count += 1

            self._persist_plan(plan)

            if should_escalate(result, plan):
                events.append(
                    ArchitectEvent(
                        task_id=entry.task_id,
                        event_type="alert",
                        stage=entry.stage,
                        summary=result.summary,
                        payload={
                            "noProgressCount": plan.no_progress_count,
                            "repeatedErrorCount": plan.repeated_error_count,
                        },
                    )
                )

        return events

    def recover(self) -> None:
        """On restart: read all persisted plans, reschedule missed deadlines."""
        from bridge.supervision.recovery import (
            compute_missed_stages,
            recover_plans,
        )

        plans = recover_plans(self._bridge_root)
        now_monotonic = time.monotonic()

        for plan in plans:
            self._plans[plan.task_id] = plan

            if plan.cancelled:
                continue

            missed = compute_missed_stages(plan, now_wallclock=time.strftime(
                "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
            ))

            for stage in missed:
                result = self._inspector.inspect(plan.task_id, stage, plan)
                if stage not in plan.completed_stages:
                    plan.completed_stages.append(stage)

                if result.progress_hash is not None:
                    if plan.last_progress_hash == result.progress_hash:
                        plan.no_progress_count += 1
                    else:
                        plan.no_progress_count = 0
                        plan.last_progress_hash = result.progress_hash

                if result.error_signature is not None:
                    plan.repeated_error_count += 1

            self._persist_plan(plan)

            from datetime import datetime, timedelta

            wc = plan.running_at
            if wc.endswith("Z"):
                wc = wc[:-1] + "+00:00"
            start_dt = datetime.fromisoformat(wc)
            now_dt = datetime.fromisoformat(
                time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
            )
            elapsed = (now_dt - start_dt).total_seconds()
            virtual_start = now_monotonic - max(elapsed, 0.0)

            self._scheduler.start_task(
                plan.task_id, virtual_start, plan.running_at
            )
    def hard_collect(
        self,
        task_id: str,
        bridge_root: Path,
        grace_seconds: int = 5,
    ) -> str:
        """Stage 5: Hard collect at T+15 (SUP-04).

        1. Stop worker (graceful stop request)
        2. Wait grace period
        3. If still alive, kill process
        4. Pull outbox
        5. Save git status + git diff
        6. Classify result and return state
        """
        bridge_root = Path(bridge_root)
        task_dir = bridge_root / "tasks" / task_id
        state_path = task_dir / "state.json"

        state: dict = {}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

        pid = state.get("processId")
        if pid and self._is_process_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            time.sleep(grace_seconds)
            if self._is_process_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        deliverables = self._collect_deliverables(task_dir, bridge_root)
        classified = classify_completion(deliverables)

        if classified == "FAILED" and deliverables.get("diff"):
            classified = "ASSISTANCE_REQUIRED"

        self._save_salvage(task_dir, deliverables)

        return classified

    def cleanup(
        self,
        task_id: str,
        bridge_root: Path,
    ) -> str:
        """Stage 6: Cleanup at T+16 (SUP-05).

        Converge all orphan states. No new work is created.
        Returns the final state the task was converged to.
        """
        bridge_root = Path(bridge_root)
        task_dir = bridge_root / "tasks" / task_id
        state_path = task_dir / "state.json"

        state: dict = {}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

        pid = state.get("processId")
        if pid and self._is_process_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        current_status = state.get("status") or state.get("state") or ""
        if current_status == "RUNNING":
            deliverables = self._collect_deliverables(task_dir, bridge_root)
            classified = classify_completion(deliverables)
            if classified == "FAILED" and deliverables.get("diff"):
                classified = "ASSISTANCE_REQUIRED"
            state["status"] = classified
            state["state"] = classified
            state["revision"] = int(state.get("revision", 0)) + 1
            try:
                state_path.write_text(
                    json.dumps(state, indent=2), encoding="utf-8"
                )
            except OSError:
                pass
            return classified

        return current_status

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    @staticmethod
    def _collect_deliverables(task_dir: Path, bridge_root: Path) -> dict:
        """Collect deliverables from task directory and outbox."""
        deliverables: dict = {}

        outbox = task_dir / "outbox"
        if outbox.exists():
            for path in outbox.iterdir():
                if path.is_file():
                    deliverables[path.name] = str(path)

        result_path = task_dir / "RESULT.md"
        if result_path.exists():
            deliverables["result"] = True

        tests_path = task_dir / "TESTS.md"
        if tests_path.exists():
            deliverables["tests"] = True

        assistance_path = task_dir / "ASSISTANCE_REQUEST.md"
        if assistance_path.exists():
            deliverables["assistance"] = True

        try:
            diff_result = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True, text=True, timeout=10,
                cwd=bridge_root,
            )
            if diff_result.stdout.strip():
                deliverables["diff"] = diff_result.stdout
        except (subprocess.TimeoutExpired, OSError):
            pass

        return deliverables

    @staticmethod
    def _save_salvage(task_dir: Path, deliverables: dict) -> None:
        """Save salvage data for post-mortem analysis."""
        salvage_dir = task_dir / "salvage"
        salvage_dir.mkdir(parents=True, exist_ok=True)
        try:
            (salvage_dir / "deliverables.json").write_text(
                json.dumps(deliverables, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass
