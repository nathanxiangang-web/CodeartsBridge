# AI生成
"""Tests for Phase 3: task, dispatch, worker, cli."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bridge.task import create_task, get_meta, get_instruction_context, write_review_pass, write_review_fix
from bridge.dispatch import select_dispatch_plan, check_worker_transport_compatibility, DispatchPlan
from bridge.state import get_state, set_state, READY, QUEUED, DONE, REVIEW_REQUIRED, FIX_REQUIRED
from bridge.atomic import atomic_write_json


BRIDGE_ROOT = Path(__file__).parent.parent


class TestTask:
    def test_create_task(self, tmp_path):
        tasks_root = tmp_path / "tasks"
        tdir = create_task(
            tasks_root=tasks_root,
            task_id="test-001",
            project_id="test-project",
            worker_id="test-worker",
            role="implement",
        )
        assert tdir.is_dir()
        assert (tdir / "META.json").is_file()
        assert (tdir / "inbox" / "001-TASK.md").is_file()
        assert (tdir / "outbox").is_dir()

        meta = get_meta(tdir)
        assert meta["taskId"] == "test-001"
        assert meta["projectId"] == "test-project"
        assert meta["workerId"] == "test-worker"

    def test_create_task_with_file(self, tmp_path):
        task_file = tmp_path / "task.md"
        task_file.write_text("# TASK\nDo something.\n")
        tdir = create_task(
            tasks_root=tmp_path / "tasks",
            task_id="test-002",
            project_id="proj",
            task_file=str(task_file),
        )
        content = (tdir / "inbox" / "001-TASK.md").read_text()
        assert "Do something" in content

    def test_review_pass(self, tmp_path):
        tdir = create_task(
            tasks_root=tmp_path / "tasks",
            task_id="test-003",
            project_id="proj",
        )
        write_review_pass(tdir, 1)
        instructions = get_instruction_context(tdir)
        assert any("PASS" in p for p in instructions)

    def test_review_fix(self, tmp_path):
        tdir = create_task(
            tasks_root=tmp_path / "tasks",
            task_id="test-004",
            project_id="proj",
        )
        write_review_fix(tdir, "Fix the bug.", 1)
        instructions = get_instruction_context(tdir)
        assert any("FIX" in p for p in instructions)


class TestDispatch:
    def test_transport_compatibility(self):
        assert check_worker_transport_compatibility("local", "local")
        assert check_worker_transport_compatibility("ssh", "ssh")
        assert check_worker_transport_compatibility("ssh", "remote-worktree")
        assert not check_worker_transport_compatibility("local", "ssh")
        assert not check_worker_transport_compatibility("local", "remote-worktree")

    def test_empty_dispatch(self, tmp_path):
        tasks_root = tmp_path / "tasks"
        tasks_root.mkdir()
        plan = select_dispatch_plan(tasks_root, BRIDGE_ROOT, max_workers=4)
        assert len(plan.plan) == 0
        assert len(plan.skipped) == 0

    def test_dispatch_with_ready_task(self, tmp_path):
        tasks_root = tmp_path / "tasks"
        tasks_root.mkdir()
        tdir = create_task(
            tasks_root=tasks_root,
            task_id="dispatch-001",
            project_id="cloudsite-rc1-w01",
            worker_id="bus-w01-dev",
            workspace_mode="existing",
        )
        set_state(tdir, READY, message="ready")

        plan = select_dispatch_plan(tasks_root, BRIDGE_ROOT, max_workers=4)
        assert len(plan.plan) == 1
        assert plan.plan[0].task_id == "dispatch-001"

    def test_dispatch_respects_max_workers(self, tmp_path):
        tasks_root = tmp_path / "tasks"
        tasks_root.mkdir()
        for i in range(6):
            tdir = create_task(
                tasks_root=tasks_root,
                task_id=f"max-{i:03d}",
                project_id="cloudsite-rc1-w01",
                worker_id="bus-w01-dev",
                workspace_mode="existing",
            )
            set_state(tdir, READY, message="ready")

        plan = select_dispatch_plan(tasks_root, BRIDGE_ROOT, max_workers=2)
        assert len(plan.plan) <= 2

    def test_dispatch_skips_non_candidate(self, tmp_path):
        tasks_root = tmp_path / "tasks"
        tasks_root.mkdir()
        tdir = create_task(
            tasks_root=tasks_root,
            task_id="skip-001",
            project_id="cloudsite-rc1-w01",
            worker_id="bus-w01-dev",
            workspace_mode="existing",
        )
        set_state(tdir, DONE, message="done")

        plan = select_dispatch_plan(tasks_root, BRIDGE_ROOT, max_workers=4)
        assert len(plan.plan) == 0

    def test_dispatch_checks_dependencies(self, tmp_path):
        tasks_root = tmp_path / "tasks"
        tasks_root.mkdir()
        # Create a dependency task that is not DONE
        dep_dir = create_task(
            tasks_root=tasks_root,
            task_id="dep-001",
            project_id="cloudsite-rc1-w01",
            worker_id="bus-w01-dev",
            workspace_mode="existing",
        )
        set_state(dep_dir, READY, message="ready")

        # Create a task that depends on it
        tdir = create_task(
            tasks_root=tasks_root,
            task_id="dependent-001",
            project_id="cloudsite-rc1-w02",
            worker_id="bus-w02-dev",
            workspace_mode="existing",
            depends_on=["dep-001"],
        )
        set_state(tdir, READY, message="ready")

        plan = select_dispatch_plan(tasks_root, BRIDGE_ROOT, max_workers=4)
        # dep-001 should be planned, dependent-001 should be skipped
        planned_ids = {item.task_id for item in plan.plan}
        skipped_ids = {s.task_id for s in plan.skipped}
        assert "dep-001" in planned_ids
        assert "dependent-001" in skipped_ids


class TestCLI:
    def test_build_parser(self):
        from bridge.cli import build_parser
        parser = build_parser()
        # Just verify it doesn't crash
        args = parser.parse_args(["bootstrap"])
        assert args.command == "bootstrap"

    def test_doctor(self, capsys):
        from bridge.cli import cmd_doctor
        import argparse
        args = argparse.Namespace()
        rc = cmd_doctor(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "Bridge" in captured.out

    def test_status_empty(self, capsys, tmp_path, monkeypatch):
        from bridge.cli import cmd_status
        import argparse
        # Mock bridge root
        monkeypatch.setattr("bridge.cli._bridge_root", lambda: tmp_path)
        (tmp_path / "tasks").mkdir()
        args = argparse.Namespace()
        rc = cmd_status(args)
        assert rc == 0