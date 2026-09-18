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

    def test_register_preserves_canonical_registry_metadata(self, tmp_path):
        from bridge.application.projects import register_project, list_projects

        pf = tmp_path / "projects.json"
        pf.write_text(json.dumps({
            "schemaVersion": 7,
            "defaults": {"model": "keep-me", "timeoutMinutes": 42},
            "projects": [{"id": "existing", "projectRoot": "/existing"}],
        }), encoding="utf-8")

        register_project(tmp_path, {"id": "new", "projectRoot": "/new"})

        raw = json.loads(pf.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["schemaVersion"] == 7
        assert raw["defaults"] == {"model": "keep-me", "timeoutMinutes": 42}
        assert [p["id"] for p in raw["projects"]] == ["existing", "new"]
        assert len(list_projects(tmp_path)) == 2

    def test_duplicate_project_id_is_rejected_without_corruption(self, tmp_path):
        from bridge.application.projects import register_project

        register_project(tmp_path, {"id": "p1"})
        with pytest.raises(ValueError, match="already registered"):
            register_project(tmp_path, {"projectId": "p1"})

        raw = json.loads((tmp_path / "projects.json").read_text(encoding="utf-8"))
        assert len(raw["projects"]) == 1

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

    def test_status_update_preserves_canonical_registry_metadata(self, tmp_path):
        from bridge.application.workers import update_worker_status

        wf = tmp_path / "workers.json"
        wf.write_text(json.dumps({
            "schemaVersion": 3,
            "defaults": {"model": "keep-worker-default", "concurrencyLimit": 2},
            "workers": [{"id": "w1", "enabled": True, "status": "online"}],
        }), encoding="utf-8")

        updated = update_worker_status(tmp_path, "w1", "offline")
        assert updated["status"] == "offline"

        raw = json.loads(wf.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["schemaVersion"] == 3
        assert raw["defaults"]["model"] == "keep-worker-default"
        assert raw["workers"][0]["status"] == "offline"

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

    def test_task_assignments_reads_scheduler_runtime_store(self, tmp_path):
        from bridge.application.queries import get_task_assignments

        runtime = tmp_path / "runtime" / "assignments"
        runtime.mkdir(parents=True)
        (runtime / "a-runtime.json").write_text(json.dumps({
            "assignmentId": "a-runtime",
            "taskId": "t-runtime",
            "workerId": "w1",
            "role": "implement",
            "finishedAt": None,
        }), encoding="utf-8")

        result = get_task_assignments(tmp_path, "t-runtime")
        assert len(result) == 1
        assert result[0]["assignmentId"] == "a-runtime"

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

    def test_save_writes_canonical_runtime_file(self, tmp_path):
        from bridge.application.assignments import save_assignment

        save_assignment(tmp_path, {
            "assignmentId": "runtime-a1",
            "workerId": "w1",
            "taskId": "t1",
            "finishedAt": None,
        })

        path = tmp_path / "runtime" / "assignments" / "runtime-a1.json"
        assert path.is_file()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["workerId"] == "w1"
        assert not (tmp_path / "assignments.json").exists()

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

    def test_active_worker_assignments_use_finished_at(self, tmp_path):
        from bridge.application.assignments import save_assignment, get_active_assignments_for_worker

        save_assignment(tmp_path, {
            "assignmentId": "active-v2",
            "workerId": "w1",
            "taskId": "t1",
            "finishedAt": None,
        })
        save_assignment(tmp_path, {
            "assignmentId": "finished-v2",
            "workerId": "w1",
            "taskId": "t2",
            "finishedAt": "2026-09-18T00:00:00+00:00",
        })

        active = get_active_assignments_for_worker(tmp_path, "w1")
        assert [a["assignmentId"] for a in active] == ["active-v2"]

    def test_count_for_worker(self, tmp_path):
        from bridge.application.assignments import save_assignment, get_assignment_count_for_worker
        save_assignment(tmp_path, {"assignmentId": "a1", "workerId": "w1", "status": "active"})
        save_assignment(tmp_path, {"assignmentId": "a2", "workerId": "w1", "status": "active"})
        assert get_assignment_count_for_worker(tmp_path, "w1") == 2


# ─── Core Registry Defaults ──────────────────────────────────────────────────

class TestCoreRegistryDefaults:
    def test_scheduler_worker_registry_applies_defaults(self):
        from bridge.core.models import WorkersRegistry

        reg = WorkersRegistry.from_dict({
            "defaults": {
                "transport": "ssh",
                "model": "default-model",
                "concurrencyLimit": 3,
                "capabilities": ["implement", "test"],
            },
            "workers": [
                {"id": "inherits"},
                {"id": "override", "concurrencyLimit": 1, "capabilities": ["review"]},
            ],
        })

        inherited = reg.get_worker("inherits")
        overridden = reg.get_worker("override")

        assert inherited is not None
        assert inherited.transport == "ssh"
        assert inherited.model == "default-model"
        assert inherited.concurrency_limit == 3
        assert inherited.roles == ["implement", "test"]

        assert overridden is not None
        assert overridden.concurrency_limit == 1
        assert overridden.roles == ["review"]
        assert overridden.model == "default-model"

    def test_scheduler_project_registry_applies_defaults(self):
        from bridge.core.models import Registry

        reg = Registry.from_dict({
            "defaults": {
                "transport": "local",
                "model": "default-project-model",
                "timeoutMinutes": 42,
            },
            "projects": [
                {"id": "inherits", "projectRoot": "/tmp/inherits"},
                {
                    "id": "override",
                    "projectRoot": "/tmp/override",
                    "model": "override-model",
                },
            ],
        })

        inherited = reg.get_project("inherits")
        overridden = reg.get_project("override")

        assert inherited is not None
        assert inherited.transport == "local"
        assert inherited.model == "default-project-model"
        assert inherited.timeout_minutes == 42

        assert overridden is not None
        assert overridden.model == "override-model"
        assert overridden.timeout_minutes == 42


# ─── DispatchService ─────────────────────────────────────────────────────────

class TestDispatchService:
    @staticmethod
    def _setup_ready_task(tmp_path, task_id="dispatch-task"):
        from bridge.application.task_service import create_task

        (tmp_path / "workers.json").write_text(json.dumps({
            "schemaVersion": 1,
            "defaults": {
                "transport": "ssh",
                "capabilities": ["implement"],
                "concurrencyLimit": 1,
                "enabled": True,
            },
            "workers": [{"id": "w1"}],
        }), encoding="utf-8")
        (tmp_path / "projects.json").write_text(json.dumps({
            "schemaVersion": 1,
            "defaults": {},
            "projects": [{
                "id": "p1",
                "transport": "ssh",
                "projectRoot": "/srv/project",
            }],
        }), encoding="utf-8")

        create_task(
            bridge_root=tmp_path,
            project_id="p1",
            worker_id=None,
            role="implement",
            task_id=task_id,
            task_file=None,
        )
        return tmp_path / "tasks" / task_id

    def test_dry_run_uses_current_scheduler_and_releases_lease(self, tmp_path):
        from bridge.application.dispatch_service import dispatch_tasks
        from bridge.core.state import get_state

        task_dir = self._setup_ready_task(tmp_path)
        result = dispatch_tasks(tmp_path, dry_run=True)

        assert result.planned == 1
        assert result.dispatched == 0
        assert result.assignments[0]["workerId"] == "w1"
        assert get_state(task_dir)["state"] == "READY"

        leases_dir = tmp_path / "runtime" / "leases"
        assert not leases_dir.exists() or list(leases_dir.glob("*.json")) == []
        assignments_dir = tmp_path / "runtime" / "assignments"
        assert list(assignments_dir.glob("*.json")) == []

    def test_dispatch_persists_assignment_and_runtime_worker(self, tmp_path):
        from bridge.application.dispatch_service import dispatch_tasks
        from bridge.core.state import get_state

        task_dir = self._setup_ready_task(tmp_path)
        result = dispatch_tasks(tmp_path, dry_run=False)

        assert result.planned == 1
        assert result.dispatched == 1
        assert result.assignments[0]["workerId"] == "w1"

        state = get_state(task_dir)
        assert state["state"] == "QUEUED"
        assert state["status"] == "QUEUED"
        assert state["assignedWorkerId"] == "w1"

        assignments = list((tmp_path / "runtime" / "assignments").glob("*.json"))
        leases = list((tmp_path / "runtime" / "leases").glob("*.json"))
        assert len(assignments) == 1
        assert len(leases) == 1
