# AI生成
"""Architect AI loop: planning tasks from requirements and reviewing Worker output.

The Architect never writes implementation code. It only:
- Plans: generates task definitions (META.json + inbox/TASK.md) from requirements
- Reviews: inspects Worker output and produces PASS/FIX verdicts

Review verdicts are deterministic for clear cases:
- PASS: RESULT.md exists AND TESTS.md shows all tests passing (failed == 0)
- FIX: RESULT.md missing OR TESTS.md shows failures (failed > 0)

For ambiguous cases (RESULT.md exists but TESTS.md unparseable), the Architect
invokes the reasoning model via the codearts CLI.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .atomic import atomic_write_json, atomic_write_text, read_json_or_none
from .codearts import (
    find_codearts_cli,
    resolve_model,
    new_worker_run_arguments,
    THINK_LANGUAGE_DIRECTIVE,
)
from .config import assert_safe_id
from .state import (
    get_state,
    set_state,
    REVIEW_REQUIRED,
    FIX_REQUIRED,
    DONE,
    READY,
)
from .core.state import CREATED, APPROVED
from .application.review_service import review_pass, review_fix
from .task import read_outbox_summary


# --- Data classes ---

@dataclass
class TaskPlan:
    """Result of planning a task from a requirement."""
    task_id: str
    project_id: str
    role: str
    meta_path: str
    inbox_path: str
    objective: str
    acceptance_criteria: list[str]


@dataclass
class ReviewVerdict:
    """Result of reviewing a completed task."""
    task_id: str
    decision: str
    reason: str
    fix_task_id: str | None = None
    fix_task_dir: str | None = None


@dataclass
class ArchitectResult:
    """Summary of an architect loop cycle."""
    reviewed: int = 0
    passed: int = 0
    fixed: int = 0
    errors: list[str] = field(default_factory=list)
    planned: int = 0
    verdicts: list[ReviewVerdict] = field(default_factory=list)


# --- AI invocation ---

def _invoke_architect_ai(
    prompt: str,
    task_id: str,
    project_root: str | Path | None = None,
    timeout_seconds: int = 120,
) -> str:
    """Invoke the codearts CLI with the architect role reasoning model."""
    cli = find_codearts_cli()
    if not cli:
        raise RuntimeError("codearts CLI not found")

    model = resolve_model(role="architect")
    args = new_worker_run_arguments(
        prompt=prompt,
        model=model,
        mode_flag=None,
        task_id=task_id,
    )

    cwd = str(project_root) if project_root else None
    r = subprocess.run(
        [cli] + args,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        cwd=cwd,
    )
    return r.stdout


# --- Planning ---

def _generate_task_id(requirement: str) -> str:
    """Generate a task ID from a requirement string."""
    words = re.sub(r"[^A-Za-z0-9 ]", "", requirement).strip().split()[:4]
    slug = "-".join(w.lower() for w in words) or "task"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"p2-{slug}-{timestamp}"


def _build_planning_prompt(requirement: str, project_id: str) -> str:
    """Build the AI prompt for planning a task from a requirement."""
    return (
        f"You are the Architect. Plan a single engineering task from this requirement.\n\n"
        f"Project: {project_id}\n"
        f"Requirement: {requirement}\n\n"
        f'Output a JSON object: {{"objective": "...", '
        f'"acceptanceCriteria": ["..."], "dependencies": ["task-id"], "role": "implement"}}\n\n'
        f"Constraints:\n"
        f"- The task must be narrowly scoped (one bounded engineering unit)\n"
        f"- Do not write implementation code, only the task definition\n"
        f"- Acceptance criteria must be testable\n"
        f"{THINK_LANGUAGE_DIRECTIVE}"
    )


def _parse_planning_response(response: str) -> dict:
    """Parse the AI planning response into a task definition dict."""
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return {}


def plan_task(
    requirement: str,
    bridge_root: Path,
    project_id: str,
    task_id: str | None = None,
    ai_invoke: Callable[[str, str], str] | None = None,
) -> TaskPlan:
    """Plan a task from a requirement string.

    Generates META.json + inbox/TASK.md with objective, dependencies,
    and acceptance criteria. Uses the codearts CLI architect role for reasoning.
    """
    bridge_root = Path(bridge_root)
    assert_safe_id(project_id, "ProjectId")

    if task_id is None:
        task_id = _generate_task_id(requirement)
    assert_safe_id(task_id, "TaskId")

    prompt = _build_planning_prompt(requirement, project_id)
    if ai_invoke is not None:
        response = ai_invoke(prompt, task_id)
    else:
        response = _invoke_architect_ai(prompt, task_id)

    plan_data = _parse_planning_response(response)
    objective = plan_data.get("objective", requirement)
    acceptance_criteria = plan_data.get("acceptanceCriteria", [])
    dependencies = plan_data.get("dependencies", [])
    role = plan_data.get("role", "implement")

    task_dir = bridge_root / "tasks" / task_id
    if task_dir.exists():
        raise ValueError(f"Task directory already exists: {task_dir}")

    (task_dir / "inbox").mkdir(parents=True)
    (task_dir / "outbox").mkdir(parents=True)

    meta = {
        "schemaVersion": 2,
        "taskId": task_id,
        "projectId": project_id,
        "workerId": None,
        "role": role,
        "requiredSkills": [],
        "dependsOn": dependencies,
        "priority": 50,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "execution": {
            "preferredWorker": None,
            "excludedWorkers": [],
            "workspace": "isolated",
            "targetMinutes": 10,
            "softTimeoutMinutes": 12,
            "hardTimeoutMinutes": 15,
        },
        "review": {
            "required": True,
            "independentWorker": True,
        },
    }
    atomic_write_json(task_dir / "META.json", meta)

    criteria_text = "\n".join(f"- {c}" for c in acceptance_criteria) or "- Task completes successfully"
    deps_text = ", ".join(dependencies) or "none"
    task_md = (
        f"# TASK: {task_id}\n\n"
        f"## Objective\n\n{objective}\n\n"
        f"## Dependencies\n\n{deps_text}\n\n"
        f"## Acceptance Criteria\n\n{criteria_text}\n"
    )
    atomic_write_text(task_dir / "inbox" / "001-TASK.md", task_md)

    set_state(task_dir, CREATED)
    set_state(task_dir, READY)

    return TaskPlan(
        task_id=task_id,
        project_id=project_id,
        role=role,
        meta_path=str(task_dir / "META.json"),
        inbox_path=str(task_dir / "inbox" / "001-TASK.md"),
        objective=objective,
        acceptance_criteria=acceptance_criteria,
    )


# --- Review ---

def _parse_tests_summary(tests_content: str) -> tuple[int, int]:
    """Parse TESTS.md to count passed and failed tests.

    Returns (passed_count, failed_count).
    """
    passed = 0
    failed = 0

    p_match = re.search(r"(?i)passed\s*[:=]\s*(\d+)", tests_content)
    f_match = re.search(r"(?i)failed\s*[:=]\s*(\d+)", tests_content)
    if p_match:
        passed = int(p_match.group(1))
    if f_match:
        failed = int(f_match.group(1))

    if passed == 0 and failed == 0:
        for line in tests_content.splitlines():
            if re.match(r"(?i)^\s*pass\b", line):
                passed += 1
            elif re.match(r"(?i)^\s*fail\b", line):
                failed += 1

    return passed, failed


def _deterministic_review(
    task_id: str,
    outbox: Path,
) -> ReviewVerdict | None:
    """Deterministic review based on outbox artifacts.

    Returns a ReviewVerdict for clear cases, None for ambiguous cases.
    """
    result_md = outbox / "RESULT.md"
    tests_md = outbox / "TESTS.md"

    if not result_md.is_file():
        return ReviewVerdict(
            task_id=task_id,
            decision="FIX",
            reason="RESULT.md missing from outbox",
        )

    if not tests_md.is_file():
        return None

    tests_content = tests_md.read_text(encoding="utf-8")
    passed, failed = _parse_tests_summary(tests_content)

    if failed > 0:
        return ReviewVerdict(
            task_id=task_id,
            decision="FIX",
            reason=f"TESTS.md reports {failed} failed test(s)",
        )

    if passed > 0:
        return ReviewVerdict(
            task_id=task_id,
            decision="PASS",
            reason=f"TESTS.md reports {passed} passed test(s), 0 failed",
        )

    return None


def _get_git_diff(task_dir: Path, bridge_root: Path) -> str:
    """Best-effort git diff inspection of the task commit."""
    try:
        r = subprocess.run(
            ["git", "diff", "HEAD~1", "HEAD", "--stat"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(bridge_root),
        )
        return r.stdout if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return ""


def review_task(
    task_id: str,
    bridge_root: Path,
    ai_invoke: Callable[[str, str], str] | None = None,
) -> ReviewVerdict:
    """Review a completed task and produce a PASS or FIX verdict.

    Deterministic for clear cases:
    - PASS: RESULT.md exists AND TESTS.md shows all tests passing
    - FIX: RESULT.md missing OR TESTS.md shows failures

    On PASS: transitions task to APPROVED; integration is a separate phase.
    On FIX: writes a numbered FIX instruction to the same task and moves it
    to FIX_REQUIRED so the scheduler can re-dispatch it.
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    outbox = task_dir / "outbox"

    if not task_dir.is_dir():
        return ReviewVerdict(
            task_id=task_id,
            decision="FIX",
            reason=f"Task directory not found: {task_dir}",
        )

    summary = read_outbox_summary(task_dir)
    verdict = _deterministic_review(task_id, outbox)

    if verdict is None:
        result_content = summary.get("RESULT.md") or ""
        tests_content = summary.get("TESTS.md") or ""
        diff_stat = summary.get("DIFF.stat") or ""
        git_diff = _get_git_diff(task_dir, bridge_root)

        prompt = (
            f"You are the Architect. Review this Worker output and decide PASS or FIX.\n\n"
            f"Task: {task_id}\n"
            f"--- RESULT.md ---\n{result_content}\n\n"
            f"--- TESTS.md ---\n{tests_content}\n\n"
            f"--- DIFF.stat ---\n{diff_stat}\n\n"
            f"--- git diff --stat ---\n{git_diff}\n\n"
            f"Output exactly one line: PASS or FIX, followed by a reason.\n"
            f"{THINK_LANGUAGE_DIRECTIVE}"
        )
        try:
            if ai_invoke is not None:
                response = ai_invoke(prompt, task_id)
            else:
                response = _invoke_architect_ai(prompt, task_id)
            first_line = response.strip().splitlines()[0] if response.strip() else ""
            if first_line.upper().startswith("PASS"):
                verdict = ReviewVerdict(task_id=task_id, decision="PASS", reason="AI review: PASS")
            else:
                verdict = ReviewVerdict(task_id=task_id, decision="FIX", reason="AI review: FIX")
        except Exception as e:
            verdict = ReviewVerdict(
                task_id=task_id,
                decision="FIX",
                reason=f"AI review unavailable, defaulting to FIX: {e}",
            )

    if verdict.decision == "PASS":
        result = review_pass(
            bridge_root,
            task_id,
            reviewer_id="architect",
            comment=verdict.reason,
        )
        if not result.success:
            raise RuntimeError(result.error)
    else:
        defect_context = verdict.reason
        if summary.get("TESTS.md"):
            defect_context += f"\n\n--- TESTS.md ---\n{summary['TESTS.md']}"
        fix_content = (
            f"# FIX: {task_id}\n\n"
            f"## Defect Context\n\n{defect_context}\n\n"
            "## Instructions\n\n"
            "Fix only the identified defects, preserve the current task scope, "
            "and update the required deliverables/tests.\n"
        )
        result = review_fix(
            bridge_root,
            task_id,
            reviewer_id="architect",
            comment=verdict.reason,
            fix_content=fix_content,
        )
        if not result.success:
            raise RuntimeError(result.error)

    return verdict


# --- Loop ---

def _scan_review_required_tasks(tasks_root: Path) -> list[str]:
    """Scan tasks/ for tasks in REVIEW_REQUIRED state."""
    task_ids: list[str] = []
    if not tasks_root.exists():
        return task_ids
    for task_dir in sorted(tasks_root.iterdir()):
        if not task_dir.is_dir():
            continue
        state = get_state(task_dir)
        status = state.get("status") or state.get("state", "")
        if status == REVIEW_REQUIRED:
            task_ids.append(task_dir.name)
    return task_ids


def architect_loop(
    bridge_root: Path,
    plan: bool = False,
    requirement: str | None = None,
    project_id: str = "bridge-dev",
    ai_invoke: Callable[[str, str], str] | None = None,
) -> ArchitectResult:
    """Run one cycle of the Architect AI loop.

    If plan=True: plan a task from the given requirement.
    Always: scan for REVIEW_REQUIRED tasks and review each.
    """
    bridge_root = Path(bridge_root)
    result = ArchitectResult()

    if plan:
        if not requirement:
            result.errors.append("Planning mode requires a requirement")
            return result
        try:
            plan_task(
                requirement=requirement,
                bridge_root=bridge_root,
                project_id=project_id,
                ai_invoke=ai_invoke,
            )
            result.planned = 1
        except Exception as e:
            result.errors.append(f"Planning failed: {e}")

    tasks_root = bridge_root / "tasks"
    review_tasks = _scan_review_required_tasks(tasks_root)

    for tid in review_tasks:
        try:
            verdict = review_task(
                task_id=tid,
                bridge_root=bridge_root,
                ai_invoke=ai_invoke,
            )
            result.reviewed += 1
            result.verdicts.append(verdict)
            if verdict.decision == "PASS":
                result.passed += 1
            else:
                result.fixed += 1
        except Exception as e:
            result.errors.append(f"Review of {tid} failed: {e}")

    return result
