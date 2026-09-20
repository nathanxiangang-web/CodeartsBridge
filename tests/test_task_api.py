# AI generated
"""Tests for BE-02 Task API enhancement: detail fields, list filters, reassign."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def api_server(tmp_path):
    """Start an API server on a random port for testing."""
    from bridge.api.server import BridgeAPIServer
    import socket

    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = BridgeAPIServer(bridge_root=tmp_path, host="127.0.0.1", port=port)
    server.start()
    time.sleep(0.2)  # Give server time to start

    yield server

    server.stop()


def _get(server, path):
    url = server.url(path)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post(server, path, data=None):
    url = server.url(path)
    body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))




def _create_task(server, tmp_path, task_id="t1", project_id="p1", worker_id="w1",
                 role="implement", priority=50):
    task_file = tmp_path / f"{task_id}.md"
    task_file.write_text(f"# Task {task_id}\n", encoding="utf-8")
    return _post(server, "/api/tasks", {
        "projectId": project_id,
        "workerId": worker_id,
        "role": role,
        "taskId": task_id,
        "taskFile": str(task_file),
        "priority": priority,
    })

class TestGetTaskDetailFields:
    """Acceptance criterion 1: GET /api/tasks/{id} returns 20+ fields."""

    def test_detail_returns_20_plus_fields(self, api_server, tmp_path):
        code, _ = _create_task(api_server, tmp_path, "detail-task")
        assert code == 201

        code, data = _get(api_server, "/api/tasks/detail-task")
        assert code == 200

        expected_fields = [
            "taskId", "state", "workerId", "attempt", "meta",
            "projectId", "role", "priority", "dependsOn", "requiredSkills",
            "baseline", "createdAt",
            "queuedAt", "startedAt", "runningAt", "finishedAt", "doneAt",
            "heartbeatSummary", "heartbeatThink", "heartbeatTool",
            "processId", "exitCode", "message",
            "targetMinutes", "softTimeoutMinutes", "hardTimeoutMinutes",
            "tokens", "outbox", "result", "tests",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
        assert len(data) >= 20

    def test_detail_includes_timeline_fields(self, api_server, tmp_path):
        from bridge.state import set_state, CREATED, READY, QUEUED, STARTING, RUNNING
        task_dir = tmp_path / "tasks" / "timeline-task"
        task_dir.mkdir(parents=True)
        (task_dir / "META.json").write_text(json.dumps({
            "schemaVersion": 2,
            "taskId": "timeline-task",
            "projectId": "p1",
            "workerId": "w1",
            "role": "implement",
            "priority": 50,
            "execution": {"targetMinutes": 10, "softTimeoutMinutes": 25, "hardTimeoutMinutes": 30},
            "review": {"required": True, "independentWorker": True},
        }), encoding="utf-8")
        set_state(task_dir, CREATED)
        set_state(task_dir, READY)
        set_state(task_dir, QUEUED)
        set_state(task_dir, STARTING)
        set_state(task_dir, RUNNING)

        code, data = _get(api_server, "/api/tasks/timeline-task")
        assert code == 200
        assert data["queuedAt"] is not None
        assert data["startedAt"] is not None
        assert data["runningAt"] is not None

    def test_detail_includes_outbox_files(self, api_server, tmp_path):
        code, _ = _create_task(api_server, tmp_path, "outbox-task")
        assert code == 201

        outbox_dir = tmp_path / "tasks" / "outbox-task" / "outbox"
        (outbox_dir / "RESULT.md").write_text("# RESULT\nAll good.\n", encoding="utf-8")
        (outbox_dir / "TESTS.md").write_text("# TESTS\n5 passed.\n", encoding="utf-8")

        code, data = _get(api_server, "/api/tasks/outbox-task")
        assert code == 200
        names = [f["name"] for f in data["outbox"]]
        assert "RESULT.md" in names
        assert "TESTS.md" in names
        assert data["result"] == "# RESULT\nAll good.\n"
        assert data["tests"] == "# TESTS\n5 passed.\n"

    def test_detail_includes_timeout_and_review_config(self, api_server, tmp_path):
        task_file = tmp_path / "config-task.md"
        task_file.write_text("# Config Task\n", encoding="utf-8")
        code, _ = _post(api_server, "/api/tasks", {
            "taskId": "config-task",
            "projectId": "p1",
            "workerId": "w1",
            "role": "implement",
            "taskFile": str(task_file),
            "execution": {
                "targetMinutes": 7,
                "softTimeoutMinutes": 9,
                "hardTimeoutMinutes": 11,
            },
            "review": {"required": False, "independentWorker": False},
        })
        assert code == 201

        code, data = _get(api_server, "/api/tasks/config-task")
        assert code == 200
        assert data["targetMinutes"] == 7
        assert data["softTimeoutMinutes"] == 9
        assert data["hardTimeoutMinutes"] == 11
        assert data["reviewRequired"] is False
        assert data["independentReview"] is False

    def test_detail_includes_tokens_and_evidence(self, api_server, tmp_path):
        task_dir = tmp_path / "tasks" / "evidence-task"
        task_dir.mkdir(parents=True)
        (task_dir / "META.json").write_text(json.dumps({
            "schemaVersion": 2,
            "taskId": "evidence-task",
            "projectId": "p1",
            "workerId": "w1",
            "role": "implement",
            "priority": 50,
        }), encoding="utf-8")
        (task_dir / "state.json").write_text(json.dumps({
            "state": "DONE",
            "status": "DONE",
            "tokens": {"input": 100, "output": 50},
            "commitSha": "abc123",
            "workspacePath": "/tmp/work",
        }), encoding="utf-8")

        code, data = _get(api_server, "/api/tasks/evidence-task")
        assert code == 200
        assert data["tokens"] == {"input": 100, "output": 50}
        assert data["commitSha"] == "abc123"
        assert data["workspacePath"] == "/tmp/work"

    def test_detail_not_found(self, api_server):
        code, data = _get(api_server, "/api/tasks/nonexistent")
        assert code == 404


class TestListTaskFilters:
    """Acceptance criterion 2: GET /api/tasks filters work."""

    def _setup_multi_tasks(self, server, tmp_path):
        _create_task(server, tmp_path, "task-a", project_id="bridge-dev", worker_id="w1", role="implement", priority=10)
        _create_task(server, tmp_path, "task-b", project_id="bridge-dev", worker_id="w2", role="review", priority=20)
        _create_task(server, tmp_path, "task-c", project_id="other-proj", worker_id="w1", role="implement", priority=30)

    def test_filter_by_status(self, api_server, tmp_path):
        self._setup_multi_tasks(api_server, tmp_path)
        (tmp_path / "tasks" / "task-a" / "state.json").write_text(
            json.dumps({"state": "RUNNING", "status": "RUNNING"}), encoding="utf-8")

        code, data = _get(api_server, "/api/tasks?status=RUNNING")
        assert code == 200
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["taskId"] == "task-a"

    def test_filter_by_state_alias(self, api_server, tmp_path):
        self._setup_multi_tasks(api_server, tmp_path)
        (tmp_path / "tasks" / "task-b" / "state.json").write_text(
            json.dumps({"state": "RUNNING", "status": "RUNNING"}), encoding="utf-8")

        code, data = _get(api_server, "/api/tasks?state=RUNNING")
        assert code == 200
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["taskId"] == "task-b"

    def test_filter_by_project(self, api_server, tmp_path):
        self._setup_multi_tasks(api_server, tmp_path)

        code, data = _get(api_server, "/api/tasks?project=bridge-dev")
        assert code == 200
        assert len(data["tasks"]) == 2
        assert all(t["projectId"] == "bridge-dev" for t in data["tasks"])

    def test_filter_by_worker(self, api_server, tmp_path):
        self._setup_multi_tasks(api_server, tmp_path)

        code, data = _get(api_server, "/api/tasks?worker=w1")
        assert code == 200
        assert len(data["tasks"]) == 2
        assert all(t["workerId"] == "w1" for t in data["tasks"])

    def test_filter_by_role(self, api_server, tmp_path):
        self._setup_multi_tasks(api_server, tmp_path)

        code, data = _get(api_server, "/api/tasks?role=review")
        assert code == 200
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["taskId"] == "task-b"

    def test_filter_by_search(self, api_server, tmp_path):
        self._setup_multi_tasks(api_server, tmp_path)

        code, data = _get(api_server, "/api/tasks?search=task-b")
        assert code == 200
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["taskId"] == "task-b"

    def test_filter_by_priority(self, api_server, tmp_path):
        self._setup_multi_tasks(api_server, tmp_path)

        code, data = _get(api_server, "/api/tasks?priority=20")
        assert code == 200
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["taskId"] == "task-b"

    def test_combined_filters(self, api_server, tmp_path):
        self._setup_multi_tasks(api_server, tmp_path)

        code, data = _get(api_server, "/api/tasks?project=bridge-dev&worker=w1")
        assert code == 200
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["taskId"] == "task-a"

    def test_status_and_project_combined(self, api_server, tmp_path):
        _create_task(api_server, tmp_path, "r1", project_id="bridge-dev", worker_id="w1")
        _create_task(api_server, tmp_path, "r2", project_id="bridge-dev", worker_id="w2")
        _create_task(api_server, tmp_path, "r3", project_id="other", worker_id="w1")
        for tid in ("r1", "r3"):
            (tmp_path / "tasks" / tid / "state.json").write_text(
                json.dumps({"state": "RUNNING", "status": "RUNNING"}), encoding="utf-8")

        code, data = _get(api_server, "/api/tasks?status=RUNNING&project=bridge-dev")
        assert code == 200
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["taskId"] == "r1"

    def test_no_filter_returns_all(self, api_server, tmp_path):
        self._setup_multi_tasks(api_server, tmp_path)

        code, data = _get(api_server, "/api/tasks")
        assert code == 200
        assert len(data["tasks"]) == 3


class TestReassignTask:
    """Acceptance criterion 3: POST /api/tasks/{id}/reassign."""

    def test_reassign_updates_worker(self, api_server, tmp_path):
        code, _ = _create_task(api_server, tmp_path, "reassign-task", worker_id="w1")
        assert code == 201

        code, data = _post(api_server, "/api/tasks/reassign-task/reassign", {"workerId": "w2"})
        assert code == 200
        assert data["taskId"] == "reassign-task"
        assert data["oldWorkerId"] == "w1"
        assert data["workerId"] == "w2"

        code, data = _get(api_server, "/api/tasks/reassign-task")
        assert code == 200
        assert data["workerId"] == "w2"

    def test_reassign_accepts_snake_case(self, api_server, tmp_path):
        code, _ = _create_task(api_server, tmp_path, "snake-reassign", worker_id="w1")
        assert code == 201

        code, data = _post(api_server, "/api/tasks/snake-reassign/reassign", {"worker_id": "w3"})
        assert code == 200
        assert data["workerId"] == "w3"

    def test_reassign_missing_worker_id(self, api_server, tmp_path):
        code, _ = _create_task(api_server, tmp_path, "no-worker-task")
        assert code == 201

        code, data = _post(api_server, "/api/tasks/no-worker-task/reassign", {})
        assert code == 400
        assert "workerId" in data["error"]

    def test_reassign_task_not_found(self, api_server):
        code, data = _post(api_server, "/api/tasks/nonexistent/reassign", {"workerId": "w1"})
        assert code == 404

    def test_reassign_updates_state_assigned_worker(self, api_server, tmp_path):
        code, _ = _create_task(api_server, tmp_path, "state-reassign", worker_id="w1")
        assert code == 201

        code, data = _post(api_server, "/api/tasks/state-reassign/reassign", {"workerId": "w2"})
        assert code == 200

        state = json.loads(
            (tmp_path / "tasks" / "state-reassign" / "state.json").read_text(encoding="utf-8")
        )
        assert state["assignedWorkerId"] == "w2"

    def test_reassign_updates_meta_worker(self, api_server, tmp_path):
        code, _ = _create_task(api_server, tmp_path, "meta-reassign", worker_id="w1")
        assert code == 201

        code, data = _post(api_server, "/api/tasks/meta-reassign/reassign", {"workerId": "w2"})
        assert code == 200

        meta = json.loads(
            (tmp_path / "tasks" / "meta-reassign" / "META.json").read_text(encoding="utf-8")
        )
        assert meta["workerId"] == "w2"

    def test_reassign_rejects_unsafe_worker_id(self, api_server, tmp_path):
        code, _ = _create_task(api_server, tmp_path, "unsafe-reassign")
        assert code == 201

        code, data = _post(api_server, "/api/tasks/unsafe-reassign/reassign", {"workerId": "../escape"})
        assert code == 400
        assert "workerId" in data["error"]
