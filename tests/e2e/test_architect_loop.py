# AI生成
"""E2E tests for P2-02: Architect AI loop."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.architect_loop import (
    plan_task,
    review_task,
    architect_loop,
    TaskPlan,
    ReviewVerdict,
    ArchitectResult,
    _parse_tests_summary,
    _deterministic_review,
)
from bridge.state import (
    REVIEW_REQUIRED,
    APPROVED,
    FIX_REQUIRED,
    CANCELLED,
    DONE,
    READY,
    CREATED,
)


# --- Helpers ---

def _create_task_with_state(
    bridge_root: Path,
    task_id: str,
    state: str = "REVIEW_REQUIRED",
    project_id: str = "test-local",
    role: str = "implement",
    depends_on: list[str] | None = None,
) -> Path:
    """Create a task directory with state.json and META.json."""
    task_dir = bridge_root / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "inbox").mkdir(exist_ok=True)
    (task_dir / "outbox").mkdir(exist_ok=True)

    state_data = {
        "schemaVersion": 1,
        "taskId": task_id,
        "state": state,
        "status": state,
        "attempt": 1,
    }
    (task_dir / "state.json").write_text(
        json.dumps(state_data, indent=2), encoding="utf-8"
    )

    meta = {
        "schemaVersion": 2,
        "taskId": task_id,
        "projectId": project_id,
        "role": role,
        "dependsOn": depends_on or [],
        "priority": 0,
        "createdAt": "2026-09-18T00:00:00+00:00",
    }
    (task_dir / "META.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return task_dir


def _write_outbox(
    task_dir: Path,
    result_md: str | None = None,
    tests_md: str | None = None,
    diff_stat: str | None = None,
) -> None:
    """Write outbox artifacts for a task."""
    outbox = task_dir / "outbox"
    outbox.mkdir(exist_ok=True)
    if result_md is not None:
        (outbox / "RESULT.md").write_text(result_md, encoding="utf-8")
    if tests_md is not None:
        (outbox / "TESTS.md").write_text(tests_md, encoding="utf-8")
    if diff_stat is not None:
        (outbox / "DIFF.stat").write_text(diff_stat, encoding="utf-8")


def _get_task_state(bridge_root: Path, task_id: str) -> str:
    task_dir = bridge_root / "tasks" / task_id
    data = json.loads(
        (task_dir / "state.json").read_text(encoding="utf-8")
    )
    return data.get("status") or data.get("state", "")


def _mock_ai_planner(prompt: str, task_id: str) -> str:
    """Mock AI that returns a valid planning response."""
    return json.dumps({
        "objective": "Implement feature X",
        "acceptanceCriteria": ["Feature X works", "Tests pass"],
        "dependencies": [],
        "role": "implement",
    })


def _mock_ai_pass_reviewer(prompt: str, task_id: str) -> str:
    """Mock AI that always returns PASS."""
    return "PASS - all good\n"


def _mock_ai_fix_reviewer(prompt: str, task_id: str) -> str:
    """Mock AI that always returns FIX."""
    return "FIX - issues found\n"


# --- Tests ---

class TestReviewValidOutput:
    """Test 1: Review a task with valid output -> PASS -> state DONE."""

    def test_valid_output_passes_to_done(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(
            task_dir,
            result_md="# RESULT\n\nTask completed successfully.\n",
            tests_md="# TESTS\n\npassed: 5\nfailed: 0\n",
            diff_stat="2 files changed\n",
        )

        verdict = review_task("t1", bridge_root)

        assert verdict.decision == "PASS"
        assert verdict.fix_task_id is None
        assert _get_task_state(bridge_root, "t1") == DONE

    def test_pass_verdict_has_reason(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(
            task_dir,
            result_md="# RESULT\n\nDone.\n",
            tests_md="passed: 3, failed: 0\n",
        )

        verdict = review_task("t1", bridge_root)

        assert verdict.decision == "PASS"
        assert "passed" in verdict.reason

    def test_pass_with_pass_fail_line_format(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(
            task_dir,
            result_md="# RESULT\n\nDone.\n",
            tests_md="PASS test_a\nPASS test_b\nPASS test_c\n",
        )

        verdict = review_task("t1", bridge_root)

        assert verdict.decision == "PASS"
        assert _get_task_state(bridge_root, "t1") == DONE


class TestReviewInvalidOutput:
    """Test 2: Review a task with invalid output -> FIX -> new fix task created."""

    def test_missing_result_md_creates_fix(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(
            task_dir,
            result_md=None,
            tests_md="passed: 5, failed: 0\n",
        )

        verdict = review_task("t1", bridge_root)

        assert verdict.decision == "FIX"
        assert verdict.fix_task_id is not None
        assert _get_task_state(bridge_root, "t1") == CANCELLED

    def test_failing_tests_creates_fix(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(
            task_dir,
            result_md="# RESULT\n\nSome issues.\n",
            tests_md="passed: 3, failed: 2\n",
        )

        verdict = review_task("t1", bridge_root)

        assert verdict.decision == "FIX"
        assert verdict.fix_task_id is not None
        assert _get_task_state(bridge_root, "t1") == CANCELLED

    def test_fix_task_has_ready_state(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(
            task_dir,
            result_md=None,
        )

        verdict = review_task("t1", bridge_root)
        fix_state = _get_task_state(bridge_root, verdict.fix_task_id)
        assert fix_state == READY

    def test_fix_task_has_fix_instruction(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(task_dir, result_md=None)

        verdict = review_task("t1", bridge_root)
        fix_dir = bridge_root / "tasks" / verdict.fix_task_id
        fix_files = list((fix_dir / "inbox").glob("*.md"))
        assert len(fix_files) >= 1
        content = fix_files[0].read_text(encoding="utf-8")
        assert "FIX" in content


class TestFixTaskLinking:
    """Test 3: FIX task is linked to original via dependsOn."""

    def test_fix_task_depends_on_original(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(task_dir, result_md=None)

        verdict = review_task("t1", bridge_root)
        fix_meta = json.loads(
            (bridge_root / "tasks" / verdict.fix_task_id / "META.json").read_text()
        )
        assert fix_meta["dependsOn"] == ["t1"]

    def test_fix_task_has_parent_task_id(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(task_dir, result_md=None)

        verdict = review_task("t1", bridge_root)
        fix_meta = json.loads(
            (bridge_root / "tasks" / verdict.fix_task_id / "META.json").read_text()
        )
        assert fix_meta.get("parentTaskId") == "t1"

    def test_fix_task_inherits_project(self, bridge_root):
        task_dir = _create_task_with_state(
            bridge_root, "t1", state="REVIEW_REQUIRED", project_id="my-project"
        )
        _write_outbox(task_dir, result_md=None)

        verdict = review_task("t1", bridge_root)
        fix_meta = json.loads(
            (bridge_root / "tasks" / verdict.fix_task_id / "META.json").read_text()
        )
        assert fix_meta["projectId"] == "my-project"


    def test_fix_task_dependency_is_ready_after_original_is_superseded(self, bridge_root):
        from bridge.scheduler.dependency import is_dependency_ready

        task_dir = _create_task_with_state(
            bridge_root, "t1", state="REVIEW_REQUIRED"
        )
        _write_outbox(task_dir, result_md=None)

        verdict = review_task("t1", bridge_root)
        fix_meta = json.loads(
            (bridge_root / "tasks" / verdict.fix_task_id / "META.json").read_text()
        )

        assert _get_task_state(bridge_root, "t1") == CANCELLED
        assert is_dependency_ready(
            fix_meta["dependsOn"], bridge_root / "tasks"
        ) is True

    def test_fix_task_inherits_execution_context(self, bridge_root):
        task_dir = _create_task_with_state(
            bridge_root, "t1", state="REVIEW_REQUIRED"
        )
        meta_path = task_dir / "META.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.update({
            "requiredSkills": ["python"],
            "priority": 88,
            "baseline": "abc123",
            "execution": {
                "preferredWorker": "old-worker",
                "excludedWorkers": ["w4"],
                "workspace": "worktree",
                "targetMinutes": 7,
                "softTimeoutMinutes": 9,
                "hardTimeoutMinutes": 12,
            },
        })
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        _write_outbox(task_dir, result_md=None)

        verdict = review_task("t1", bridge_root)
        fix_meta = json.loads(
            (bridge_root / "tasks" / verdict.fix_task_id / "META.json").read_text()
        )

        assert fix_meta["requiredSkills"] == ["python"]
        assert fix_meta["priority"] == 88
        assert fix_meta["baseline"] == "abc123"
        assert fix_meta["execution"]["preferredWorker"] is None
        assert fix_meta["execution"]["excludedWorkers"] == ["w4"]
        assert fix_meta["execution"]["workspace"] == "worktree"
        assert fix_meta["execution"]["targetMinutes"] == 7
        assert fix_meta["execution"]["softTimeoutMinutes"] == 9
        assert fix_meta["execution"]["hardTimeoutMinutes"] == 12


class TestPlanningMode:
    """Test 4: Planning mode creates well-formed META.json + inbox/TASK.md."""

    def test_plan_creates_meta_and_inbox(self, bridge_root):
        plan = plan_task(
            requirement="Add user authentication endpoint",
            bridge_root=bridge_root,
            project_id="test-local",
            task_id="p2-auth-test",
            ai_invoke=_mock_ai_planner,
        )

        assert plan.task_id == "p2-auth-test"
        assert plan.project_id == "test-local"

        task_dir = bridge_root / "tasks" / "p2-auth-test"
        assert (task_dir / "META.json").is_file()
        assert (task_dir / "inbox" / "001-TASK.md").is_file()

    def test_plan_meta_is_well_formed(self, bridge_root):
        plan = plan_task(
            requirement="Add feature X",
            bridge_root=bridge_root,
            project_id="test-local",
            task_id="p2-feat-x",
            ai_invoke=_mock_ai_planner,
        )

        meta = json.loads(
            (bridge_root / "tasks" / "p2-feat-x" / "META.json").read_text()
        )
        assert meta["schemaVersion"] == 2
        assert meta["taskId"] == "p2-feat-x"
        assert meta["projectId"] == "test-local"
        assert meta["role"] == "implement"
        assert "createdAt" in meta
        assert "review" in meta
        assert meta["review"]["required"] is True

    def test_plan_inbox_has_objective(self, bridge_root):
        plan = plan_task(
            requirement="Add feature Y",
            bridge_root=bridge_root,
            project_id="test-local",
            task_id="p2-feat-y",
            ai_invoke=_mock_ai_planner,
        )

        task_md = (
            bridge_root / "tasks" / "p2-feat-y" / "inbox" / "001-TASK.md"
        ).read_text(encoding="utf-8")
        assert "# TASK" in task_md
        assert "## Objective" in task_md
        assert "## Acceptance Criteria" in task_md

    def test_plan_task_has_ready_state(self, bridge_root):
        plan = plan_task(
            requirement="Add feature Z",
            bridge_root=bridge_root,
            project_id="test-local",
            task_id="p2-feat-z",
            ai_invoke=_mock_ai_planner,
        )

        state = _get_task_state(bridge_root, "p2-feat-z")
        assert state == READY

    def test_plan_auto_generates_task_id(self, bridge_root):
        plan = plan_task(
            requirement="Add some feature",
            bridge_root=bridge_root,
            project_id="test-local",
            ai_invoke=_mock_ai_planner,
        )

        assert plan.task_id.startswith("p2-")
        assert (bridge_root / "tasks" / plan.task_id / "META.json").is_file()


class TestArchitectNeverWritesCode:
    """Test 5: Architect never writes implementation code."""

    def test_planning_only_writes_task_files(self, bridge_root):
        plan = plan_task(
            requirement="Add feature A",
            bridge_root=bridge_root,
            project_id="test-local",
            task_id="p2-feat-a",
            ai_invoke=_mock_ai_planner,
        )

        task_dir = bridge_root / "tasks" / "p2-feat-a"
        all_files = list(task_dir.rglob("*"))
        file_names = [f.name for f in all_files if f.is_file()]

        assert "META.json" in file_names
        assert "001-TASK.md" in file_names
        assert "state.json" in file_names
        for name in file_names:
            assert not name.endswith(".py"), \
                f"Architect must not write .py files, found: {name}"

    def test_review_only_writes_task_files(self, bridge_root):
        task_dir = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(task_dir, result_md=None)

        verdict = review_task("t1", bridge_root)
        fix_dir = bridge_root / "tasks" / verdict.fix_task_id
        all_files = list(fix_dir.rglob("*"))
        file_names = [f.name for f in all_files if f.is_file()]

        for name in file_names:
            assert not name.endswith(".py"), \
                f"Architect must not write .py files, found: {name}"

    def test_no_src_modification(self, bridge_root):
        src_dir = bridge_root / "src"
        src_dir.mkdir(exist_ok=True)
        (src_dir / "existing.py").write_text("# existing\n", encoding="utf-8")

        plan = plan_task(
            requirement="Add feature B",
            bridge_root=bridge_root,
            project_id="test-local",
            task_id="p2-feat-b",
            ai_invoke=_mock_ai_planner,
        )

        assert (src_dir / "existing.py").read_text() == "# existing\n"
        assert len(list(src_dir.glob("*.py"))) == 1


class TestLoopMultipleTasks:
    """Test 6: Loop processes multiple REVIEW_REQUIRED tasks in one cycle."""

    def test_loop_reviews_multiple_tasks(self, bridge_root):
        t1 = _create_task_with_state(bridge_root, "t1", state="REVIEW_REQUIRED")
        _write_outbox(t1, result_md="# R\n", tests_md="passed: 1, failed: 0\n")

        t2 = _create_task_with_state(bridge_root, "t2", state="REVIEW_REQUIRED")
        _write_outbox(t2, result_md=None)

        t3 = _create_task_with_state(bridge_root, "t3", state="REVIEW_REQUIRED")
        _write_outbox(t3, result_md="# R\n", tests_md="passed: 2, failed: 0\n")

        result = architect_loop(bridge_root)

        assert result.reviewed == 3
        assert result.passed == 2
        assert result.fixed == 1
        assert len(result.verdicts) == 3

    def test_loop_skips_non_review_tasks(self, bridge_root):
        t1 = _create_task_with_state(bridge_root, "t1", state="RUNNING")
        _write_outbox(t1, result_md="# R\n", tests_md="passed: 1, failed: 0\n")

        t2 = _create_task_with_state(bridge_root, "t2", state="DONE")

        result = architect_loop(bridge_root)

        assert result.reviewed == 0
        assert result.passed == 0
        assert result.fixed == 0

    def test_loop_with_planning(self, bridge_root):
        result = architect_loop(
            bridge_root,
            plan=True,
            requirement="Add feature C",
            project_id="test-local",
            ai_invoke=_mock_ai_planner,
        )

        assert result.planned == 1
        assert result.reviewed == 0
        assert len(result.errors) == 0

    def test_loop_planning_without_requirement_errors(self, bridge_root):
        result = architect_loop(bridge_root, plan=True)

        assert result.planned == 0
        assert len(result.errors) == 1
        assert "requirement" in result.errors[0].lower()

    def test_loop_empty_bridge(self, bridge_root):
        result = architect_loop(bridge_root)

        assert result.reviewed == 0
        assert result.passed == 0
        assert result.fixed == 0
        assert result.planned == 0


class TestTestsSummaryParsing:
    """Unit tests for TESTS.md parsing."""

    def test_passed_failed_format(self):
        p, f = _parse_tests_summary("passed: 5\nfailed: 0\n")
        assert p == 5
        assert f == 0

    def test_inline_format(self):
        p, f = _parse_tests_summary("passed: 3, failed: 2\n")
        assert p == 3
        assert f == 2

    def test_pass_fail_lines(self):
        p, f = _parse_tests_summary("PASS test_a\nPASS test_b\nFAIL test_c\n")
        assert p == 2
        assert f == 1

    def test_empty_content(self):
        p, f = _parse_tests_summary("")
        assert p == 0
        assert f == 0

    def test_case_insensitive(self):
        p, f = _parse_tests_summary("PASSED: 4\nFAILED: 1\n")
        assert p == 4
        assert f == 1


class TestDeterministicReview:
    """Unit tests for the deterministic review function."""

    def test_missing_result_md_returns_fix(self, tmp_path):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        verdict = _deterministic_review("t1", outbox)
        assert verdict is not None
        assert verdict.decision == "FIX"

    def test_pass_with_passing_tests(self, tmp_path):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "RESULT.md").write_text("# R\n", encoding="utf-8")
        (outbox / "TESTS.md").write_text("passed: 5, failed: 0\n", encoding="utf-8")
        verdict = _deterministic_review("t1", outbox)
        assert verdict is not None
        assert verdict.decision == "PASS"

    def test_fix_with_failing_tests(self, tmp_path):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "RESULT.md").write_text("# R\n", encoding="utf-8")
        (outbox / "TESTS.md").write_text("passed: 3, failed: 2\n", encoding="utf-8")
        verdict = _deterministic_review("t1", outbox)
        assert verdict is not None
        assert verdict.decision == "FIX"

    def test_ambiguous_returns_none(self, tmp_path):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "RESULT.md").write_text("# R\n", encoding="utf-8")
        verdict = _deterministic_review("t1", outbox)
        assert verdict is None
