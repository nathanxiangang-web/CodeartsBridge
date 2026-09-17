# AI生成
"""Tests for Phase 8 additional Application Layer services.

Covers: ProjectService, WorkerService, QueryService, AssignmentService.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ─── ProjectService ──────────────────────────────────────────────────────────

class TestProjectService:
    def test_list_empty(self, tmp_path):
        from bridge.application.projects import list_projects
        assert list_projects(tmp_path) == []

    def test_register_and_list(self, tmp_path):
        from bridge.application.projects import register_project, list_projects
        p = register_project(tmp_path, {"projectId": "p1", "name": "Test"})
        assert p["projectId"] == "p1"
        assert len(list_projects(tmp_path)) == 1

    def test_get_project(self, tmp_path):
        from bridge.application.projects import register_project, get_project
        register_project(tmp_path, {"projectId": "p1", "name": "A"})
        register_project(tmp_path, {"projectId": "p2", "name": "B"})
        assert get_project(tmp_path, "p1")["name"] == "A"
        assert get_project(tmp_path, "p2")["name"] == "B"
        assert get_project(tmp_path, "p3") is None

    def test_unregister(self, tmp_path):
        from bridge.application.projects import register_project, unregister_project, list_projects
        register_project(tmp_path, {"projectId": "p1"})
        assert unregister_project(tmp_path, "p1") is True
        assert list_projects(tmp_path) == []
        assert unregister_project(tmp_path, "p1") is False


# ─── WorkerService ───────────────────────────────────────────────────────────

class TestWorkerService:
    def test_list_empty(self, tmp_path):
        from bridge.application.workers import list_workers
        assert list_workers(tmp_path) == []

    def test_register_and_get(self, tmp_path):
        from bridge.application.workers import register_worker, get_worker
        register_worker(tmp_path, {"id": "w1", "roles": ["implement"]})
        w = get_worker(tmp_path, "w1")
        assert w is not None and w["id"] == "w1"
        assert get_worker(tmp_path, "w2") is None

    def test_update_status(self, tmp_path):
        from bridge.application.workers import register_worker, update_worker_status, get_worker
        register_worker(tmp_path, {"id": "w1", "status": "online"})
        update_worker_status(tmp_path, "w1", "offline")
        assert get_worker(tmp_path, "w1")["status"] == "offline"

    def test_get_available(self, tmp_path):
        from bridge.application.workers import register_worker, get_available_workers
        register_worker(tmp_path, {"id": "w1", "enabled": True})
        register_worker(tmp_path, {"id": "w2", "enabled": False})
        available = get_available_workers(tmp_path)
        assert len(available) == 1 and available[0]["id"] == "w1"


# ─── QueryService ────────────────────────────────────────────────────────────

class TestQueryService:
    def test_dashboard_summary_empty(self, tmp_path):
        from bridge.application.queries import get_dashboard_summary
        summary = get_dashboard_summary(tmp_path)
        assert summary["total_tasks"] == 0
        assert summary["projects"] == 0
        assert summary["workers"]["total"] == 0

    def test_dashboard_summary_with_tasks(self, tmp_path):
        from bridge.application.queries import get_dashboard_summary
        from bridge.core.state import set_state, CREATED, READY
        for i in range(3):
            td = tmp_path / "tasks" / f"t{i}"
            td.mkdir(parents=True)
            set_state(td, CREATED)
            set_state(td, READY)
        summary = get_dashboard_summary(tmp_path)
        assert summary["total_tasks"] == 3
        assert summary["tasks"].get("READY") == 3

    def test_recent_events_empty(self, tmp_path):
        from bridge.application.queries import get_recent_events
        assert get_recent_events(tmp_path) == []

    def test_task_assignments_empty(self, tmp_path):
        from bridge.application.queries import get_task_assignments
        assert get_task_assignments(tmp_path, "t1") == []

    def test_worker_assignments(self, tmp_path):
        from bridge.application.queries import get_worker_assignments
        af = tmp_path / "assignments.json"
        af.write_text(json.dumps([
            {"assignmentId": "a1", "workerId": "w1", "taskId": "t1"},
            {"assignmentId": "a2", "workerId": "w2", "taskId": "t2"},
        ]))
        result = get_worker_assignments(tmp_path, "w1")
        assert len(result) == 1 and result[0]["assignmentId"] == "a1"


# ─── AssignmentService ───────────────────────────────────────────────────────

class TestAssignmentService:
    def test_list_empty(self, tmp_path):
        from bridge.application.assignments import list_assignments
        assert list_assignments(tmp_path) == []

    def test_save_and_get(self, tmp_path):
        from bridge.application.assignments import save_assignment, get_assignment
        save_assignment(tmp_path, {"assignmentId": "a1", "workerId": "w1", "taskId": "t1"})
        a = get_assignment(tmp_path, "a1")
        assert a is not None and a["workerId"] == "w1"

    def test_save_updates_existing(self, tmp_path):
        from bridge.application.assignments import save_assignment, list_assignments
        save_assignment(tmp_path, {"assignmentId": "a1", "status": "active"})
        save_assignment(tmp_path, {"assignmentId": "a1", "status": "completed"})
        all_a = list_assignments(tmp_path)
        assert len(all_a) == 1
        assert all_a[0]["status"] == "completed"

    def test_active_for_worker(self, tmp_path):
        from bridge.application.assignments import save_assignment, get_active_assignments_for_worker
        save_assignment(tmp_path, {"assignmentId": "a1", "workerId": "w1", "status": "active"})
        save_assignment(tmp_path, {"assignmentId": "a2", "workerId": "w1", "status": "completed"})
        active = get_active_assignments_for_worker(tmp_path, "w1")
        assert len(active) == 1 and active[0]["assignmentId"] == "a1"

    def test_count_for_worker(self, tmp_path):
        from bridge.application.assignments import save_assignment, get_assignment_count_for_worker
        save_assignment(tmp_path, {"assignmentId": "a1", "workerId": "w1", "status": "active"})
        save_assignment(tmp_path, {"assignmentId": "a2", "workerId": "w1", "status": "active"})
        assert get_assignment_count_for_worker(tmp_path, "w1") == 2