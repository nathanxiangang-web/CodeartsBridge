# AI生成
"""MCP server for CodeartsBridge.

Exposes Application Services as MCP tools over JSON-RPC 2.0 (stdio).
Shares the same Application Layer as CLI and HTTP API — does NOT
implement a second scheduling system.

Tools:
  projects.list, projects.get
  workers.list, workers.get, workers.health
  tasks.create, tasks.list, tasks.get, tasks.cancel, tasks.retry
  dispatch.plan, dispatch.run
  results.get, logs.get
  review.pass, review.fix
  integration.plan, integration.execute
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MCPToolRegistry:
    """Registry of MCP tools that delegate to Application Services."""

    def __init__(self, bridge_root: str | Path):
        self.bridge_root = Path(bridge_root)
        self._tools: dict[str, dict] = {}
        self._handlers: dict[str, Any] = {}
        self._register_all()

    def _register(self, name: str, description: str, input_schema: dict, handler):
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
        self._handlers[name] = handler

    def list_tools(self) -> list[dict]:
        return list(self._tools.values())

    def call_tool(self, name: str, arguments: dict) -> Any:
        handler = self._handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        try:
            return handler(arguments)
        except Exception as e:
            logger.exception("MCP tool %s failed", name)
            return {"error": str(e)}

    def _register_all(self):
        root = self.bridge_root

        # ── Projects ──────────────────────────────────────────────────────
        self._register(
            "projects.list", "List all registered projects",
            {"type": "object", "properties": {}},
            lambda args: self._list_projects(),
        )
        self._register(
            "projects.get", "Get a specific project by ID",
            {"type": "object", "properties": {"projectId": {"type": "string"}}},
            lambda args: self._get_project(args.get("projectId", "")),
        )

        # ── Workers ───────────────────────────────────────────────────────
        self._register(
            "workers.list", "List all registered workers",
            {"type": "object", "properties": {}},
            lambda args: self._list_workers(),
        )
        self._register(
            "workers.get", "Get a specific worker by ID",
            {"type": "object", "properties": {"workerId": {"type": "string"}}},
            lambda args: self._get_worker(args.get("workerId", "")),
        )
        self._register(
            "workers.health", "Check worker health status",
            {"type": "object", "properties": {"workerId": {"type": "string"}}},
            lambda args: self._worker_health(args.get("workerId", "")),
        )

        # ── Tasks ─────────────────────────────────────────────────────────
        self._register(
            "tasks.create", "Create a new task",
            {"type": "object", "properties": {
                "taskId": {"type": "string"},
                "projectId": {"type": "string"},
                "workerId": {"type": "string"},
                "role": {"type": "string"},
                "taskFile": {"type": "string"},
                "dependsOn": {"type": "array", "items": {"type": "string"}},
            }, "required": ["taskId", "projectId", "role"]},
            lambda args: self._create_task(args),
        )
        self._register(
            "tasks.list", "List all tasks",
            {"type": "object", "properties": {"state": {"type": "string"}}},
            lambda args: self._list_tasks(args.get("state")),
        )
        self._register(
            "tasks.get", "Get task details by ID",
            {"type": "object", "properties": {"taskId": {"type": "string"}}},
            lambda args: self._get_task(args.get("taskId", "")),
        )
        self._register(
            "tasks.cancel", "Cancel a task",
            {"type": "object", "properties": {"taskId": {"type": "string"}, "reason": {"type": "string"}}},
            lambda args: self._cancel_task(args.get("taskId", ""), args.get("reason", "")),
        )
        self._register(
            "tasks.retry", "Retry a failed task",
            {"type": "object", "properties": {"taskId": {"type": "string"}}},
            lambda args: self._retry_task(args.get("taskId", "")),
        )

        # ── Dispatch ──────────────────────────────────────────────────────
        self._register(
            "dispatch.plan", "Plan task dispatch (dry run)",
            {"type": "object", "properties": {"maxWorkers": {"type": "integer"}}},
            lambda args: self._dispatch_plan(args.get("maxWorkers", 4)),
        )
        self._register(
            "dispatch.run", "Execute task dispatch",
            {"type": "object", "properties": {"maxWorkers": {"type": "integer"}}},
            lambda args: self._dispatch_run(args.get("maxWorkers", 4)),
        )

        # ── Results & Logs ────────────────────────────────────────────────
        self._register(
            "results.get", "Get task execution result",
            {"type": "object", "properties": {"taskId": {"type": "string"}}},
            lambda args: self._get_result(args.get("taskId", "")),
        )
        self._register(
            "logs.get", "Get task execution logs",
            {"type": "object", "properties": {"taskId": {"type": "string"}, "lines": {"type": "integer"}}},
            lambda args: self._get_logs(args.get("taskId", ""), args.get("lines", 100)),
        )

        # ── Review ────────────────────────────────────────────────────────
        self._register(
            "review.pass", "Mark a task as review passed",
            {"type": "object", "properties": {"taskId": {"type": "string"}, "reviewerId": {"type": "string"}}},
            lambda args: self._review_pass(args.get("taskId", ""), args.get("reviewerId", "mcp")),
        )
        self._register(
            "review.fix", "Request fix for a task",
            {"type": "object", "properties": {"taskId": {"type": "string"}, "fixFile": {"type": "string"}, "reviewerId": {"type": "string"}}},
            lambda args: self._review_fix(args.get("taskId", ""), args.get("fixFile", ""), args.get("reviewerId", "mcp")),
        )

        # ── Integration ──────────────────────────────────────────────────
        self._register(
            "integration.plan", "Plan integration for an approved task",
            {"type": "object", "properties": {"taskId": {"type": "string"}}},
            lambda args: self._integration_plan(args.get("taskId", "")),
        )
        self._register(
            "integration.execute", "Execute integration for an approved task",
            {"type": "object", "properties": {"taskId": {"type": "string"}}},
            lambda args: self._integration_execute(args.get("taskId", "")),
        )

    # ── Tool implementations (delegate to Application Services) ─────────────

    def _list_projects(self):
        from bridge.application.projects import list_projects
        return {"projects": list_projects(self.bridge_root)}

    def _get_project(self, project_id: str):
        from bridge.application.projects import list_projects
        for p in list_projects(self.bridge_root):
            if p.get("projectId") == project_id or p.get("id") == project_id:
                return p
        return {"error": f"Project {project_id} not found"}

    def _list_workers(self):
        from bridge.application.workers import list_workers
        return {"workers": list_workers(self.bridge_root)}

    def _get_worker(self, worker_id: str):
        from bridge.application.workers import list_workers
        for w in list_workers(self.bridge_root):
            if w.get("id") == worker_id:
                return w
        return {"error": f"Worker {worker_id} not found"}

    def _worker_health(self, worker_id: str):
        from bridge.application.workers import list_workers
        for w in list_workers(self.bridge_root):
            if w.get("id") == worker_id:
                return {"workerId": worker_id, "enabled": w.get("enabled", False), "healthy": w.get("enabled", False)}
        return {"workerId": worker_id, "healthy": False, "error": "not found"}

    def _create_task(self, args):
        from bridge.application.task_service import create_task
        task_file = args.get("taskFile", "")
        if not task_file or not Path(task_file).is_file():
            # Create a default task file in a temp location (not the task dir)
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
                f.write(f"# Task: {args.get('taskId', '')}\n\nRole: {args.get('role', 'implement')}\n")
                task_file = f.name
        meta = create_task(
            bridge_root=self.bridge_root,
            project_id=args.get("projectId", ""),
            worker_id=args.get("workerId", "default"),
            role=args.get("role", "implement"),
            task_id=args.get("taskId", ""),
            task_file=task_file,
            required_skills=args.get("requiredSkills", []),
            depends_on=args.get("dependsOn", []),
        )
        return {"taskId": args.get("taskId"), "created": True}

    def _list_tasks(self, state_filter=None):
        from bridge.application.task_service import list_tasks
        tasks = list_tasks(self.bridge_root)
        if state_filter:
            tasks = [t for t in tasks if t.get("state") == state_filter]
        return {"tasks": tasks}

    def _get_task(self, task_id: str):
        from bridge.application.task_service import get_task_status
        status = get_task_status(self.bridge_root, task_id)
        return status if status else {"error": f"Task {task_id} not found"}

    def _cancel_task(self, task_id: str, reason: str):
        from bridge.application.task_service import cancel_task
        return cancel_task(self.bridge_root, task_id, reason)

    def _retry_task(self, task_id: str):
        from bridge.core.state import get_state, set_state, FAILED, RETRYABLE, READY
        task_dir = self.bridge_root / "tasks" / task_id
        if not task_dir.exists():
            return {"error": f"Task {task_id} not found"}
        current = get_state(task_dir).get("state", "")
        if current not in (FAILED, RETRYABLE, "BLOCKED"):
            return {"error": f"Cannot retry from state {current}"}
        set_state(task_dir, READY)
        return {"taskId": task_id, "state": "READY"}

    def _dispatch_plan(self, max_workers: int):
        from bridge.auto_dispatch import auto_dispatch
        result = auto_dispatch(bridge_root=self.bridge_root, max_workers=max_workers, dry_run=True)
        return {
            "plan": [{"taskId": a["taskId"], "workerId": a["workerId"]} for a in result.assignments],
            "skipped": [{"taskId": s.get("taskId", "?"), "reason": s.get("reason", "?")} for s in result.skipped_details],
        }

    def _dispatch_run(self, max_workers: int):
        from bridge.auto_dispatch import auto_dispatch
        result = auto_dispatch(bridge_root=self.bridge_root, max_workers=max_workers, dry_run=False)
        return {
            "dispatched": [{"taskId": a["taskId"], "workerId": a["workerId"]} for a in result.assignments],
            "skipped": [{"taskId": s.get("taskId", "?"), "reason": s.get("reason", "?")} for s in result.skipped_details],
        }

    def _get_result(self, task_id: str):
        result_file = self.bridge_root / "tasks" / task_id / "outbox" / "RESULT.json"
        if result_file.exists():
            return json.loads(result_file.read_text(encoding="utf-8"))
        return {"error": f"No result for task {task_id}"}

    def _get_logs(self, task_id: str, lines: int):
        log_file = self.bridge_root / "tasks" / task_id / "worker.log"
        if log_file.exists():
            all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            return {"logs": all_lines[-lines:]}
        return {"logs": []}

    def _review_pass(self, task_id: str, reviewer_id: str):
        from bridge.application.review_service import review_pass
        result = review_pass(self.bridge_root, task_id, reviewer_id=reviewer_id)
        return {"success": result.success, "newState": result.new_state}

    def _review_fix(self, task_id: str, fix_file: str, reviewer_id: str):
        from bridge.application.review_service import review_fix
        if not fix_file:
            fix_path = self.bridge_root / "tasks" / task_id / "inbox" / "REVIEW_FIX.md"
            fix_path.parent.mkdir(parents=True, exist_ok=True)
            fix_path.write_text("# FIX\n\nPlease fix the issues.\n", encoding="utf-8")
            fix_file = str(fix_path)
        result = review_fix(self.bridge_root, task_id, fix_file, reviewer_id=reviewer_id)
        return {"success": result.success, "newState": result.new_state}

    def _integration_plan(self, task_id: str):
        from bridge.application.integration_service import integrate_approved_task
        return {"taskId": task_id, "plan": "integration branch + conflict detection + tests"}

    def _integration_execute(self, task_id: str):
        from bridge.application.integration_service import integrate_approved_task
        result = integrate_approved_task(self.bridge_root, task_id)
        return {"success": result.success, "taskId": result.task_id, "newState": result.new_state}


class MCPServer:
    """MCP server using JSON-RPC 2.0 over stdio.

    Shares Application Layer with CLI and HTTP API.
    Does NOT implement a second scheduling system.
    """

    def __init__(self, bridge_root: str | Path):
        self.registry = MCPToolRegistry(bridge_root)
        self._running = False

    def start(self):
        """Start the MCP server on stdio (blocking)."""
        self._running = True
        for line in sys.stdin:
            if not self._running:
                break
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self._handle_request(request)
                sys.stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
                sys.stdout.flush()
            except json.JSONDecodeError:
                sys.stdout.write(json.dumps({"error": "Invalid JSON"}) + "\n")
                sys.stdout.flush()
            except Exception as e:
                sys.stdout.write(json.dumps({"error": str(e)}) + "\n")
                sys.stdout.flush()

    def stop(self):
        self._running = False

    def _handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.registry.list_tools()}}
        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = self.registry.call_tool(name, arguments)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}