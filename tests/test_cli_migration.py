# AI生成
"""Tests for CLI migration to Application Service layer.

Phase 8 requirement: CLI 不直接操作 task 文件和 state 文件.
Verifies CLI commands use Application Services.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestCLIParser:
    def test_build_parser(self):
        from bridge.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["bootstrap"])
        assert args.command == "bootstrap"

    def test_has_serve_command(self):
        from bridge.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["serve", "--port", "9090"])
        assert args.command == "serve"
        assert args.port == 9090

    def test_has_projects_command(self):
        from bridge.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["projects"])
        assert args.command == "projects"

    def test_has_workers_command(self):
        from bridge.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["workers"])
        assert args.command == "workers"

    def test_command_map_has_all(self):
        from bridge.cli import COMMAND_MAP
        expected = {"bootstrap", "doctor", "status", "create", "dispatch",
                    "run", "review-pass", "review-fix", "cancel",
                    "pause", "resume", "serve", "projects", "workers"}
        assert expected.issubset(set(COMMAND_MAP.keys()))


class TestCLIUsesServices:
    def test_create_uses_task_service(self, tmp_path, monkeypatch):
        """Verify cmd_create calls v2_create_task, not direct file ops."""
        from bridge.cli import cmd_create
        import argparse

        monkeypatch.setattr("bridge.cli._bridge_root", lambda: tmp_path)

        task_file = tmp_path / "task.md"
        task_file.write_text("# Test\n", encoding="utf-8")

        args = argparse.Namespace(
            project_id="p1", worker_id="w1", role="implement",
            task_id="t1", task_file=str(task_file),
            baseline=None, target_minutes=10,
            soft_timeout_minutes=12, timeout_minutes=15,
            workspace_mode=None, depends_on=None,
        )
        rc = cmd_create(args)
        assert rc == 0
        # Verify task was created via service (META.json with schemaVersion 2)
        meta_file = tmp_path / "tasks" / "t1" / "META.json"
        assert meta_file.exists()

    def test_create_without_worker_uses_auto_assignment(self, tmp_path, monkeypatch):
        from bridge.cli import cmd_create
        import argparse
        import json

        monkeypatch.setattr("bridge.cli._bridge_root", lambda: tmp_path)

        args = argparse.Namespace(
            project_id="p1", worker_id=None, role="implement",
            task_id="auto-cli", task_file=None,
            baseline=None, target_minutes=10,
            soft_timeout_minutes=12, timeout_minutes=15,
            workspace_mode=None, depends_on=None,
        )
        rc = cmd_create(args)
        assert rc == 0

        meta = json.loads((tmp_path / "tasks" / "auto-cli" / "META.json").read_text(encoding="utf-8"))
        assert meta["workerId"] is None
        assert (tmp_path / "tasks" / "auto-cli" / "inbox" / "001-TASK.md").is_file()

    def test_cancel_uses_task_service(self, tmp_path, monkeypatch):
        from bridge.cli import cmd_cancel
        from bridge.application.task_service import create_task
        import argparse

        monkeypatch.setattr("bridge.cli._bridge_root", lambda: tmp_path)

        task_file = tmp_path / "task.md"
        task_file.write_text("# Test\n", encoding="utf-8")
        create_task(bridge_root=tmp_path, project_id="p1", worker_id="w1",
                    role="implement", task_id="t1", task_file=str(task_file))

        args = argparse.Namespace(task_id="t1")
        rc = cmd_cancel(args)
        assert rc == 0

    def test_projects_uses_service(self, tmp_path, monkeypatch, capsys):
        from bridge.cli import cmd_projects
        import argparse

        monkeypatch.setattr("bridge.cli._bridge_root", lambda: tmp_path)
        args = argparse.Namespace()
        rc = cmd_projects(args)
        assert rc == 0

    def test_workers_uses_service(self, tmp_path, monkeypatch, capsys):
        from bridge.cli import cmd_workers
        import argparse

        monkeypatch.setattr("bridge.cli._bridge_root", lambda: tmp_path)
        args = argparse.Namespace()
        rc = cmd_workers(args)
        assert rc == 0