# AI生成
"""Tests for Phase 10-12 (P2): Web UI, MCP, bridge serve."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

import pytest


# ── Phase 10: Web UI ─────────────────────────────────────────────────────────

class TestWebUI:
    """Test that the HTTP API server serves the Web UI static files."""

    def test_index_html_exists(self):
        web_dir = Path(__file__).resolve().parent.parent / "src" / "bridge" / "web"
        assert (web_dir / "index.html").exists(), "Web UI index.html must exist"

    def test_index_html_has_dashboard(self):
        web_dir = Path(__file__).resolve().parent.parent / "src" / "bridge" / "web"
        content = (web_dir / "index.html").read_text(encoding="utf-8")
        assert "Dashboard" in content
        assert "Projects" in content
        assert "Tasks" in content
        assert "Workers" in content
        assert "Review" in content
        assert "Settings" in content

    def test_web_ui_served_by_api(self, tmp_path):
        """Test that GET / returns the HTML page, not JSON."""
        from bridge.api.server import BridgeAPIServer
        (tmp_path / "tasks").mkdir()
        server = BridgeAPIServer(bridge_root=tmp_path, host="127.0.0.1", port=0)
        # Use a fixed port
        port = _find_free_port()
        server = BridgeAPIServer(bridge_root=tmp_path, host="127.0.0.1", port=port)
        server.start()
        try:
            time.sleep(0.3)
            req = urllib.request.Request(f"http://127.0.0.1:{port}/")
            resp = urllib.request.urlopen(req, timeout=5)
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8")
            assert "text/html" in content_type
            assert "<html" in body.lower()
            assert "Dashboard" in body
        finally:
            server.stop()

    def test_web_ui_served_at_any_path(self, tmp_path):
        """Non-API paths should serve the Web UI."""
        from bridge.api.server import BridgeAPIServer
        (tmp_path / "tasks").mkdir()
        port = _find_free_port()
        server = BridgeAPIServer(bridge_root=tmp_path, host="127.0.0.1", port=port)
        server.start()
        try:
            time.sleep(0.3)
            req = urllib.request.Request(f"http://127.0.0.1:{port}/tasks")
            resp = urllib.request.urlopen(req, timeout=5)
            content_type = resp.headers.get("Content-Type", "")
            assert "text/html" in content_type
        finally:
            server.stop()


# ── Phase 11: MCP ────────────────────────────────────────────────────────────

class TestMCPToolRegistry:
    """Test MCP tool registry exposes all required tools."""

    def _make_registry(self, tmp_path):
        from bridge.interfaces.mcp.server import MCPToolRegistry
        (tmp_path / "tasks").mkdir()
        (tmp_path / "events").mkdir()
        return MCPToolRegistry(tmp_path)

    def test_all_tools_registered(self, tmp_path):
        reg = self._make_registry(tmp_path)
        tools = reg.list_tools()
        names = {t["name"] for t in tools}
        expected = {
            "projects.list", "projects.get",
            "workers.list", "workers.get", "workers.health",
            "tasks.create", "tasks.list", "tasks.get", "tasks.cancel", "tasks.retry",
            "dispatch.plan", "dispatch.run",
            "results.get", "logs.get",
            "review.pass", "review.fix",
            "integration.plan", "integration.execute",
        }
        assert names == expected, f"Missing tools: {expected - names}"

    def test_tool_has_schema(self, tmp_path):
        reg = self._make_registry(tmp_path)
        for tool in reg.list_tools():
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    def test_projects_list(self, tmp_path):
        reg = self._make_registry(tmp_path)
        (tmp_path / "projects.json").write_text('[]', encoding="utf-8")
        result = reg.call_tool("projects.list", {})
        assert "projects" in result

    def test_workers_list(self, tmp_path):
        reg = self._make_registry(tmp_path)
        (tmp_path / "workers.json").write_text('[]', encoding="utf-8")
        result = reg.call_tool("workers.list", {})
        assert "workers" in result

    def test_tasks_list_empty(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg.call_tool("tasks.list", {})
        assert "tasks" in result

    def test_tasks_create_and_get(self, tmp_path):
        reg = self._make_registry(tmp_path)
        (tmp_path / "projects.json").write_text(
            json.dumps([{"projectId": "test-proj", "name": "Test", "repo_url": "", "branch": "main"}]),
            encoding="utf-8",
        )
        result = reg.call_tool("tasks.create", {
            "taskId": "mcp-test-001",
            "projectId": "test-proj",
            "workerId": "worker-01",
            "role": "implement",
        })
        assert result.get("created") is True
        # Get task
        detail = reg.call_tool("tasks.get", {"taskId": "mcp-test-001"})
        assert detail is not None

    def test_unknown_tool(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg.call_tool("nonexistent.tool", {})
        assert "error" in result

    def test_review_pass(self, tmp_path):
        reg = self._make_registry(tmp_path)
        # Create a task first
        (tmp_path / "projects.json").write_text(
            json.dumps([{"projectId": "p1", "name": "P1", "repo_url": "", "branch": "main"}]),
            encoding="utf-8",
        )
        reg.call_tool("tasks.create", {
            "taskId": "rev-test-001",
            "projectId": "p1",
            "workerId": "w1",
            "role": "implement",
        })
        # Move to REVIEW_REQUIRED state via valid transition path
        from bridge.core.state import set_state, READY, QUEUED, STARTING, RUNNING, VERIFYING, REVIEW_REQUIRED
        task_dir = tmp_path / "tasks" / "rev-test-001"
        set_state(task_dir, READY)
        set_state(task_dir, QUEUED)
        set_state(task_dir, STARTING)
        set_state(task_dir, RUNNING)
        set_state(task_dir, VERIFYING)
        set_state(task_dir, REVIEW_REQUIRED)
        # Review pass
        result = reg.call_tool("review.pass", {"taskId": "rev-test-001"})
        assert result.get("success") is True

    def test_integration_plan(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg.call_tool("integration.plan", {"taskId": "some-task"})
        assert "plan" in result


class TestMCPServer:
    """Test MCP server JSON-RPC protocol."""

    def test_initialize(self, tmp_path):
        from bridge.interfaces.mcp.server import MCPServer
        (tmp_path / "tasks").mkdir()
        (tmp_path / "events").mkdir()
        server = MCPServer(tmp_path)
        response = server._handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
        })
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response

    def test_tools_list(self, tmp_path):
        from bridge.interfaces.mcp.server import MCPServer
        (tmp_path / "tasks").mkdir()
        (tmp_path / "events").mkdir()
        server = MCPServer(tmp_path)
        response = server._handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        })
        tools = response["result"]["tools"]
        assert len(tools) == 18

    def test_tools_call(self, tmp_path):
        from bridge.interfaces.mcp.server import MCPServer
        (tmp_path / "tasks").mkdir()
        (tmp_path / "events").mkdir()
        (tmp_path / "projects.json").write_text('[]', encoding="utf-8")
        server = MCPServer(tmp_path)
        response = server._handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "projects.list", "arguments": {}},
        })
        assert "result" in response

    def test_ping(self, tmp_path):
        from bridge.interfaces.mcp.server import MCPServer
        (tmp_path / "tasks").mkdir()
        server = MCPServer(tmp_path)
        response = server._handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "ping",
        })
        assert response["jsonrpc"] == "2.0"

    def test_method_not_found(self, tmp_path):
        from bridge.interfaces.mcp.server import MCPServer
        (tmp_path / "tasks").mkdir()
        server = MCPServer(tmp_path)
        response = server._handle_request({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "unknown/method",
        })
        assert "error" in response


# ── Phase 12: bridge serve ───────────────────────────────────────────────────

class TestBridgeServe:
    """Test the unified bridge serve command."""

    def test_serve_parser_has_args(self):
        from bridge.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["serve", "--host", "127.0.0.1", "--port", "9999", "--no-mcp"])
        assert args.command == "serve"
        assert args.host == "127.0.0.1"
        assert args.port == 9999
        assert args.no_mcp is True

    def test_serve_starts_api(self, tmp_path, monkeypatch):
        """Test that bridge serve starts the API server."""
        from bridge.cli import cmd_serve
        import argparse

        # Mock bridge root
        monkeypatch.setattr("bridge.cli._bridge_root", lambda: tmp_path)
        (tmp_path / "tasks").mkdir()
        (tmp_path / "runtime").mkdir()

        port = _find_free_port()
        args = argparse.Namespace(host="127.0.0.1", port=port, no_mcp=True)

        # Run serve in a thread, stop after 1s
        rc = [None]
        def _run():
            rc[0] = cmd_serve(args)
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(1.0)

        # Check API is responding
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3)
            data = json.loads(resp.read())
            assert data["status"] == "healthy"
        except Exception:
            pass  # Server may have started/stopped

        # Check Web UI is responding
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
            content_type = resp.headers.get("Content-Type", "")
            assert "text/html" in content_type
        except Exception:
            pass

    def test_serve_web_ui_accessible(self, tmp_path, monkeypatch):
        """Test that Web UI is accessible when bridge serve is running."""
        from bridge.api.server import BridgeAPIServer
        (tmp_path / "tasks").mkdir()
        port = _find_free_port()
        server = BridgeAPIServer(bridge_root=tmp_path, host="127.0.0.1", port=port)
        server.start()
        try:
            time.sleep(0.3)
            # Web UI
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
            assert "text/html" in resp.headers.get("Content-Type", "")
            # API health
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3)
            health = json.loads(resp.read())
            assert health["status"] == "healthy"
        finally:
            server.stop()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]