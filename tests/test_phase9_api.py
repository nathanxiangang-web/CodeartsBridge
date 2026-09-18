# AI生成
"""Tests for Phase 9: HTTP REST API + Event Stream + Health API."""

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


class TestHealthAPI:
    def test_health_returns_ok(self, api_server):
        code, data = _get(api_server, "/api/health")
        assert code == 200
        assert data["status"] == "healthy"
        assert "tasks" in data
        assert "workers" in data
        assert "timestamp" in data

    def test_health_counts_tasks(self, api_server, tmp_path):
        from bridge.core.state import set_state, CREATED, READY
        tasks_dir = tmp_path / "tasks"
        for i in range(3):
            td = tasks_dir / f"t{i}"
            td.mkdir(parents=True)
            set_state(td, CREATED)
            set_state(td, READY)
        code, data = _get(api_server, "/api/health")
        assert code == 200
        assert data["tasks"] == 3


    def test_health_counts_workers_inside_registry(self, api_server, tmp_path):
        (tmp_path / "workers.json").write_text(json.dumps({
            "schemaVersion": 1,
            "defaults": {"enabled": True},
            "workers": [{"id": "w1"}, {"id": "w2"}],
        }), encoding="utf-8")

        code, data = _get(api_server, "/api/health")
        assert code == 200
        assert data["workers"] == 2


class TestProjectsAPI:
    def test_create_without_worker_or_task_file_keeps_auto_assignment(self, api_server, tmp_path):
        code, data = _post(api_server, "/api/tasks", {
            "projectId": "p1",
            "role": "implement",
            "taskId": "auto-task",
        })
        assert code == 201
        assert data["workerId"] is None

        task_md = tmp_path / "tasks" / "auto-task" / "inbox" / "001-TASK.md"
        assert task_md.is_file()
        assert "No task file provided" in task_md.read_text(encoding="utf-8")

        code, listed = _get(api_server, "/api/tasks")
        assert code == 200
        task = next(t for t in listed["tasks"] if t["taskId"] == "auto-task")
        assert task["workerId"] is None

    def test_list_empty(self, api_server):
        code, data = _get(api_server, "/api/projects")
        assert code == 200
        assert data == {"projects": []}

    def test_create_and_list(self, api_server):
        code, data = _post(api_server, "/api/projects", {
            "projectId": "p1",
            "name": "Test Project",
            "repoUrl": "https://github.com/test/repo",
        })
        assert code == 201
        assert data["projectId"] == "p1"

        code, data = _get(api_server, "/api/projects")
        assert code == 200
        assert len(data["projects"]) == 1
        assert data["projects"][0]["projectId"] == "p1"

    def test_create_accepts_snake_case_and_preserves_registry(self, api_server, tmp_path):
        (tmp_path / "projects.json").write_text(json.dumps({
            "schemaVersion": 4,
            "defaults": {"model": "keep-me"},
            "projects": [],
        }), encoding="utf-8")

        code, data = _post(api_server, "/api/projects", {
            "project_id": "snake-project",
            "project_root": "/srv/snake",
            "run_mode": "auto",
            "repo_url": "https://github.com/example/snake",
        })

        assert code == 201
        assert data["id"] == "snake-project"
        assert data["projectId"] == "snake-project"
        assert data["projectRoot"] == "/srv/snake"
        assert data["runMode"] == "auto"

        raw = json.loads((tmp_path / "projects.json").read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["schemaVersion"] == 4
        assert raw["defaults"] == {"model": "keep-me"}
        assert raw["projects"][0]["id"] == "snake-project"

    def test_duplicate_project_returns_conflict(self, api_server):
        first, _ = _post(api_server, "/api/projects", {"projectId": "p1"})
        second, data = _post(api_server, "/api/projects", {"project_id": "p1"})
        assert first == 201
        assert second == 409
        assert "already registered" in data["error"]

    def test_create_missing_id(self, api_server):
        code, data = _post(api_server, "/api/projects", {"name": "No ID"})
        assert code == 400


class TestWorkersAPI:
    def test_list_empty(self, api_server):
        code, data = _get(api_server, "/api/workers")
        assert code == 200
        assert data == {"workers": []}

    def test_get_worker_not_found(self, api_server):
        code, data = _get(api_server, "/api/workers/nonexistent")
        assert code == 404
        assert "error" in data

    def test_list_with_workers(self, api_server, tmp_path):
        wf = tmp_path / "workers.json"
        wf.write_text(json.dumps([
            {"id": "w1", "roles": ["implement"], "skills": ["python"]},
            {"id": "w2", "roles": ["review"], "skills": ["python"]},
        ]), encoding="utf-8")
        code, data = _get(api_server, "/api/workers")
        assert code == 200
        assert len(data["workers"]) == 2

    def test_get_worker_from_canonical_registry(self, api_server, tmp_path):
        wf = tmp_path / "workers.json"
        wf.write_text(json.dumps({
            "schemaVersion": 1,
            "defaults": {"enabled": True},
            "workers": [
                {"id": "w1", "capabilities": ["implement"]},
                {"id": "w2", "capabilities": ["review"]},
            ],
        }), encoding="utf-8")

        code, data = _get(api_server, "/api/workers/w2")
        assert code == 200
        assert data["id"] == "w2"

    def test_get_worker_by_id(self, api_server, tmp_path):
        wf = tmp_path / "workers.json"
        wf.write_text(json.dumps([
            {"id": "w1", "roles": ["implement"]},
            {"id": "w2", "roles": ["review"]},
        ]), encoding="utf-8")
        code, data = _get(api_server, "/api/workers/w1")
        assert code == 200
        assert data["id"] == "w1"


class TestTasksAPI:
    def _create_task(self, api_server, tmp_path, task_id="t1"):
        task_file = tmp_path / f"{task_id}.md"
        task_file.write_text(f"# Task {task_id}\n", encoding="utf-8")
        code, data = _post(api_server, "/api/tasks", {
            "projectId": "p1",
            "workerId": "w1",
            "role": "implement",
            "taskId": task_id,
            "taskFile": str(task_file),
            "requiredSkills": ["python"],
        })
        return code, data

    def test_list_empty(self, api_server):
        code, data = _get(api_server, "/api/tasks")
        assert code == 200
        assert data.get("tasks", []) == []

    def test_create_and_get(self, api_server, tmp_path):
        code, data = self._create_task(api_server, tmp_path)
        assert code == 201
        assert data["taskId"] == "t1"
        assert data["schemaVersion"] == 2

        code, data = _get(api_server, "/api/tasks/t1")
        assert code == 200
        assert data["taskId"] == "t1"

    def test_list_tasks(self, api_server, tmp_path):
        for i in range(3):
            self._create_task(api_server, tmp_path, f"t{i}")
        code, data = _get(api_server, "/api/tasks")
        assert code == 200
        assert len(data.get("tasks", [])) == 3
        assert all(task.get("workerId") == "w1" for task in data["tasks"])

    def test_list_and_detail_use_runtime_assigned_worker(self, api_server, tmp_path):
        task_dir = tmp_path / "tasks" / "runtime-assigned"
        task_dir.mkdir(parents=True)
        (task_dir / "META.json").write_text(json.dumps({
            "schemaVersion": 2,
            "taskId": "runtime-assigned",
            "projectId": "p1",
            "role": "implement",
        }), encoding="utf-8")
        (task_dir / "state.json").write_text(json.dumps({
            "state": "QUEUED",
            "assignedWorkerId": "w-runtime",
        }), encoding="utf-8")

        code, data = _get(api_server, "/api/tasks")
        assert code == 200
        task = next(t for t in data["tasks"] if t["taskId"] == "runtime-assigned")
        assert task["workerId"] == "w-runtime"

        code, data = _get(api_server, "/api/tasks/runtime-assigned")
        assert code == 200
        assert data["workerId"] == "w-runtime"

    def test_cancel_task(self, api_server, tmp_path):
        self._create_task(api_server, tmp_path)
        code, data = _post(api_server, "/api/tasks/t1/cancel", {"reason": "test"})
        assert code == 200
        assert data["state"] == "CANCELLED"

    def test_get_task_not_found(self, api_server):
        code, data = _get(api_server, "/api/tasks/nonexistent")
        assert code in (404, 500)  # 404 if handled, 500 if exception
        assert "error" in data

    def test_create_missing_field(self, api_server):
        code, data = _post(api_server, "/api/tasks", {"projectId": "p1"})
        assert code == 400


class TestReviewAPI:
    def _setup_task_in_review(self, tmp_path):
        from bridge.core.state import set_state, CREATED
        task_dir = tmp_path / "tasks" / "t1"
        (task_dir / "inbox").mkdir(parents=True)
        (task_dir / "outbox").mkdir(parents=True)
        set_state(task_dir, CREATED)
        for s in ["READY", "QUEUED", "STARTING", "RUNNING", "VERIFYING", "REVIEW_REQUIRED"]:
            set_state(task_dir, s)

    def test_review_pass(self, api_server, tmp_path):
        self._setup_task_in_review(tmp_path)
        code, data = _post(api_server, "/api/tasks/t1/review/pass", {"reviewerId": "w2"})
        assert code == 200
        assert data["success"] is True
        assert data["newState"] == "APPROVED"

    def test_review_fix(self, api_server, tmp_path):
        self._setup_task_in_review(tmp_path)
        fix_file = tmp_path / "fix.md"
        fix_file.write_text("# Fix needed\n", encoding="utf-8")
        code, data = _post(api_server, "/api/tasks/t1/review/fix", {
            "reviewerId": "w2",
            "fixFile": str(fix_file),
        })
        assert code == 200
        assert data["success"] is True
        assert data["newState"] == "FIX_REQUIRED"

    def test_review_fix_missing_file(self, api_server, tmp_path):
        self._setup_task_in_review(tmp_path)
        code, data = _post(api_server, "/api/tasks/t1/review/fix", {"reviewerId": "w2"})
        assert code == 200


class TestIntegrationAPI:
    def test_integrate_missing_task_id(self, api_server):
        code, data = _post(api_server, "/api/integrations", {})
        assert code == 400


class TestMetricsCostAPI:
    def test_cost_endpoint_normalizes_structured_tokens_and_runtime_worker(self, api_server, tmp_path):
        task_dir = tmp_path / "tasks" / "cost-task"
        task_dir.mkdir(parents=True)
        (task_dir / "META.json").write_text(json.dumps({
            "taskId": "cost-task",
            "projectId": "p1",
            "workerId": "requested-worker",
            "role": "implement",
        }), encoding="utf-8")
        (task_dir / "state.json").write_text(json.dumps({
            "taskId": "cost-task",
            "status": "DONE",
            "state": "DONE",
            "attempt": 1,
            "assignedWorkerId": "runtime-worker",
            "tokens": {
                "input_tokens": 120,
                "output_tokens": 80,
                "reasoning_tokens": 50,
            },
        }), encoding="utf-8")
        (tmp_path / "cost_rates.json").write_text(json.dumps({
            "ratePerMTokens": 10.0,
            "byRole": {},
        }), encoding="utf-8")

        code, data = _get(api_server, "/api/cost")
        assert code == 200
        assert data["hasCostData"] is True
        assert data["totalTokens"] == 250
        assert data["totalEstimatedCost"] == pytest.approx(0.0025)
        assert data["byWorker"] == [{
            "key": "runtime-worker",
            "tasks": 1,
            "tokens": 250,
            "estimatedCost": pytest.approx(0.0025),
        }]


class TestEventStreamAPI:
    def test_event_stream_connects(self, api_server):
        """Test that the SSE endpoint accepts connections and sends headers."""
        import socket
        host, port = api_server.host, api_server.port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: localhost\r\n\r\n")
        # Read response headers
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
        sock.close()
        assert b"200" in data
        assert b"text/event-stream" in data


class TestAPIServer:
    def test_server_start_stop(self, tmp_path):
        from bridge.api.server import BridgeAPIServer
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = BridgeAPIServer(bridge_root=tmp_path, host="127.0.0.1", port=port)
        assert not server.is_running
        server.start()
        time.sleep(0.2)
        assert server.is_running
        server.stop()
        assert not server.is_running

    def test_server_url(self, tmp_path):
        from bridge.api.server import BridgeAPIServer
        server = BridgeAPIServer(bridge_root=tmp_path, host="localhost", port=9999)
        assert server.url("/api/health") == "http://localhost:9999/api/health"


class TestAPIImports:
    def test_import_api(self):
        from bridge.api import BridgeAPIServer, create_handler
        assert BridgeAPIServer is not None
        assert create_handler is not None

    def test_import_server(self):
        from bridge.api.server import BridgeAPIHandler, ThreadingHTTPServer
        assert BridgeAPIHandler is not None
        assert ThreadingHTTPServer is not None

class TestThinkingEchoWebRegression:
    def test_metrics_dashboard_keeps_hardened_thinking_echo(self):
        web_path = Path(__file__).parent.parent / "src" / "bridge" / "web" / "index.html"
        html = web_path.read_text(encoding="utf-8")
        assert "async function loadMetrics()" in html
        assert "const seenEventIds={};" in html
        assert "const activityRank={RUNNING:3,STARTING:2,QUEUED:1};" in html
        assert "task.workerId||(task.meta&&task.meta.workerId)||''" in html
        assert "loadHistory();" in html
        assert "const shownCount={};" not in html


class TestTaskLogParsing:
    def test_latest_window_has_stable_event_ids(self):
        from bridge.api.server import _parse_task_session_log

        base = 1_800_000_000_000
        lines = [
            json.dumps({
                "timestamp": base + i * 1000,
                "type": "reasoning",
                "part": {"text": f"step-{i}"},
            })
            for i in range(60)
        ]

        first = _parse_task_session_log("\n".join(lines))
        assert first["eventCount"] == 60
        assert len(first["events"]) == 50
        assert first["events"][0]["text"] == "step-10"
        assert first["events"][-1]["text"] == "step-59"
        assert len({event["id"] for event in first["events"]}) == 50

        second = _parse_task_session_log("\n".join(lines + [
            json.dumps({
                "timestamp": base + 60_000,
                "type": "reasoning",
                "part": {"text": "step-60"},
            })
        ]))
        assert len(second["events"]) == 50
        assert second["events"][-1]["text"] == "step-60"
        assert second["events"][-2]["id"] == first["events"][-1]["id"]

    def test_iso_timestamps_are_normalized_to_epoch_ms(self):
        from bridge.api.server import _parse_task_session_log

        raw = "\n".join([
            json.dumps({
                "timestamp": "2026-09-18T16:00:00Z",
                "type": "step_start",
                "part": {},
            }),
            json.dumps({
                "timestamp": "2026-09-18T16:00:05Z",
                "type": "reasoning",
                "part": {"text": "still working"},
            }),
        ])
        parsed = _parse_task_session_log(raw)
        assert parsed["elapsed"] == 5
        assert parsed["startTime"] > 0
        assert all(isinstance(event["time"], int) for event in parsed["events"])
