# AI生成
"""HTTP API server using only Python standard library.

Endpoints:
  GET    /                      - Web UI (Dashboard)
  GET    /api/projects           - List projects
  POST   /api/projects           - Register project
  GET    /api/workers             - List workers
  GET    /api/workers/{id}        - Get worker detail
  GET    /api/tasks               - List tasks
  POST   /api/tasks               - Create task
  GET    /api/tasks/{id}          - Get task detail
  POST   /api/tasks/{id}/cancel   - Cancel task
  POST   /api/tasks/{id}/retry    - Retry task
  POST   /api/tasks/{id}/review/pass - Review pass
  POST   /api/tasks/{id}/review/fix  - Review fix
  POST   /api/integrations        - Integrate approved task
  GET    /api/events              - SSE event stream
  GET    /api/health              - Health check
"""
from __future__ import annotations

import json
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


def _parse_task_session_log(raw_text: str) -> dict:
    """Parse a CodeArts session log into a bounded, cursor-safe UI payload."""
    import hashlib
    import re
    from datetime import datetime

    raw_text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw_text)
    raw_text = re.sub(r'[\r\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw_text)

    def timestamp_ms(value):
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            # Accept both epoch seconds and epoch milliseconds.
            return int(value * 1000) if value < 100_000_000_000 else int(value)
        if isinstance(value, str):
            try:
                numeric = float(value)
                return int(numeric * 1000) if numeric < 100_000_000_000 else int(numeric)
            except ValueError:
                try:
                    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
                except ValueError:
                    return 0
        return 0

    events = []
    timestamps = []
    tool_count = 0
    reasoning_count = 0

    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.startswith("脚本启动"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        ts = timestamp_ms(obj.get("timestamp"))
        if ts:
            timestamps.append(ts)

        ptype = obj.get("type", "")
        part = obj.get("part", {})
        event_id = hashlib.sha1(line.encode("utf-8", errors="replace")).hexdigest()[:16]

        if ptype == "reasoning":
            text = part.get("text", "")
            if text:
                reasoning_count += 1
                events.append({"id": event_id, "type": "reasoning", "text": text[:200], "time": ts})
        elif ptype == "tool_use":
            tool = part.get("tool", "")
            state = part.get("state", {})
            status = state.get("status", "")
            inp = state.get("input", {})
            summary = f"{tool}"
            if tool == "read" and inp.get("filePath"):
                summary += f" {inp['filePath'].split('/')[-1]}"
            elif tool == "write" and inp.get("filePath"):
                summary += f" {inp['filePath'].split('/')[-1]}"
            elif tool == "bash" and inp.get("command"):
                summary += f" {inp['command'][:60]}"
            elif tool == "edit" and inp.get("filePath"):
                summary += f" {inp['filePath'].split('/')[-1]}"
            tool_count += 1
            events.append({"id": event_id, "type": "tool", "text": summary, "status": status, "time": ts})
        elif ptype == "step_start":
            events.append({"id": event_id, "type": "step", "text": "开始执行", "time": ts})

    start = timestamps[0] if timestamps else 0
    end = timestamps[-1] if timestamps else 0
    elapsed = max(0, (end - start) // 1000) if start and end else 0
    return {
        "startTime": start,
        "elapsed": elapsed,
        "events": events[-50:],
        "eventCount": len(events),
        "toolCount": tool_count,
        "reasoningCount": reasoning_count,
    }


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class BridgeAPIHandler(BaseHTTPRequestHandler):
    bridge_root: Path = Path(".")
    event_store = None

    def log_message(self, format, *args):
        logger.debug("API %s - %s", self.address_string(), format % args)

    def _send_json(self, code: int, data: Any):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code: int, content: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_sse(self, event_type: str, data: dict):
        line = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        self.wfile.write(line.encode("utf-8"))
        self.wfile.flush()

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _parse_path(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        return parts, query

    def _serve_static(self):
        """Serve static web UI files from src/bridge/web/."""
        web_dir = Path(__file__).resolve().parent.parent / "web"
        index_file = web_dir / "index.html"
        if index_file.exists():
            content = index_file.read_bytes()
            return self._send_html(200, content)
        return self._send_json(404, {"error": "Web UI not found"})

    def do_GET(self):
        parts, query = self._parse_path()
        # Serve web UI for non-API paths
        if not parts or parts[0] != "api":
            return self._serve_static()
        import sys; print(f"[API] {self.path}", file=sys.stderr, flush=True)
        if len(parts) < 2:
            return self._send_json(404, {"error": "Not found"})

        resource = parts[1]
        if resource == "health":
            return self._handle_health()
        if resource == "projects":
            return self._handle_list_projects()
        if resource == "workers":
            if len(parts) >= 3:
                return self._handle_get_worker(parts[2])
            return self._handle_list_workers()
        if resource == "tasks":
            if len(parts) >= 3:
                task_id = parts[2]
                if len(parts) >= 4 and parts[3] == "outbox":
                    if len(parts) >= 5:
                        return self._handle_read_outbox_file(task_id, parts[4])
                    return self._handle_list_outbox(task_id)
                if len(parts) >= 4 and parts[3] == "log":
                    return self._handle_get_task_log(task_id)
                return self._handle_get_task(task_id)
            return self._handle_list_tasks(query)
        if resource == "events":
            return self._handle_event_stream(query)
        if resource == "metrics":
            if len(parts) >= 3 and parts[2] == "history":
                return self._handle_metrics_history(query)
            return self._handle_metrics()
        if resource == "cost":
            return self._handle_cost()
        return self._send_json(404, {"error": f"Unknown endpoint: {resource}"})

    def do_POST(self):
        parts, _ = self._parse_path()
        if not parts or parts[0] != "api":
            return self._send_json(404, {"error": "Not found"})
        if len(parts) < 2:
            return self._send_json(404, {"error": "Not found"})

        resource = parts[1]
        if resource == "projects":
            return self._handle_create_project()
        if resource == "tasks":
            if len(parts) >= 3:
                task_id = parts[2]
                if len(parts) >= 4:
                    action = parts[3]
                    if action == "cancel":
                        return self._handle_cancel_task(task_id)
                    if action == "retry":
                        return self._handle_retry_task(task_id)
                    if action == "review" and len(parts) >= 5:
                        review_action = parts[4]
                        if review_action == "pass":
                            return self._handle_review_pass(task_id)
                        if review_action == "fix":
                            return self._handle_review_fix(task_id)
                return self._send_json(404, {"error": "Unknown task action"})
            return self._handle_create_task()
        if resource == "integrations":
            return self._handle_integrate()
        return self._send_json(404, {"error": f"Unknown endpoint: {resource}"})

    # ── Health ──────────────────────────────────────────────────────────────

    def _handle_health(self):
        tasks_dir = self.bridge_root / "tasks"
        task_count = 0
        running = 0
        if tasks_dir.exists():
            for d in tasks_dir.iterdir():
                if d.is_dir():
                    task_count += 1
                    sf = d / "state.json"
                    if sf.exists():
                        try:
                            s = json.loads(sf.read_text()).get("state", "")
                            if s == "RUNNING":
                                running += 1
                        except Exception:
                            pass
        worker_count = 0
        try:
            from bridge.application.workers import list_workers
            worker_count = len(list_workers(self.bridge_root))
        except Exception:
            pass
        from bridge import __version__
        from bridge.atomic import read_json_or_none

        daemon_health = read_json_or_none(
            self.bridge_root / "runtime" / "daemon" / "health.json"
        )
        pipeline_state = read_json_or_none(
            self.bridge_root / "runtime" / "pipeline-state.json"
        )

        self._send_json(200, {
            "status": "healthy",
            "version": __version__,
            "bridge_root": str(self.bridge_root),
            "tasks": task_count,
            "running": running,
            "workers": worker_count,
            "daemon": daemon_health,
            "pipeline": pipeline_state,
            "timestamp": time.time(),
        })

    # ── Projects ────────────────────────────────────────────────────────────

    def _handle_list_projects(self):
        from bridge.application.projects import list_projects
        try:
            return self._send_json(200, {"projects": list_projects(self.bridge_root)})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _handle_create_project(self):
        from bridge.application.projects import register_project

        body = self._read_body()
        project_id = body.get("projectId") or body.get("project_id") or body.get("id")
        if not project_id:
            return self._send_json(400, {"error": "projectId/project_id/id required"})

        project = dict(body)
        project["id"] = project_id
        # Keep projectId in the API response for backward compatibility.
        project.setdefault("projectId", project_id)
        project.pop("project_id", None)

        aliases = {
            "project_root": "projectRoot",
            "run_mode": "runMode",
            "repo_url": "repoUrl",
            "timeout_minutes": "timeoutMinutes",
            "ssh_host": "sshHost",
            "remote_bridge_root": "remoteBridgeRoot",
            "remote_workspace_root": "remoteWorkspaceRoot",
            "remote_cli_path": "remoteCliPath",
        }
        for source, target in aliases.items():
            if source in project:
                project.setdefault(target, project[source])
                project.pop(source, None)

        try:
            register_project(self.bridge_root, project)
            return self._send_json(201, project)
        except ValueError as e:
            return self._send_json(409, {"error": str(e)})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    # ── Workers ─────────────────────────────────────────────────────────────

    def _handle_list_workers(self):
        from bridge.application.workers import list_workers
        try:
            return self._send_json(200, {"workers": list_workers(self.bridge_root)})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _handle_get_worker(self, worker_id: str):
        from bridge.application.workers import get_worker
        try:
            worker = get_worker(self.bridge_root, worker_id)
            if worker is None:
                return self._send_json(404, {"error": f"Worker {worker_id} not found"})
            return self._send_json(200, worker)
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    # ── Tasks ───────────────────────────────────────────────────────────────

    def _handle_list_tasks(self, query: dict):
        from bridge.application.task_service import list_tasks
        try:
            tasks = list_tasks(self.bridge_root)
            state_filter = query.get("state", [None])[0]
            if state_filter:
                tasks = [t for t in tasks if t.get("state") == state_filter]
            return self._send_json(200, {"tasks": tasks})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _handle_get_task(self, task_id: str):
        from bridge.application.task_service import get_task_status
        from bridge.core.errors import TaskNotFoundError
        from bridge.state import get_state
        try:
            status = get_task_status(self.bridge_root, task_id)
            task_dir = self.bridge_root / "tasks" / task_id
            state_data = get_state(task_dir)
            status["heartbeatSummary"] = state_data.get("heartbeatSummary")
            status["heartbeatThink"] = state_data.get("heartbeatThink")
            status["heartbeatTool"] = state_data.get("heartbeatTool")
            status["lastHeartbeat"] = state_data.get("lastHeartbeat")
            status["message"] = state_data.get("message")
            return self._send_json(200, status)
        except TaskNotFoundError as e:
            return self._send_json(404, {"error": str(e)})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _handle_list_outbox(self, task_id: str):
        task_dir = self.bridge_root / "tasks" / task_id
        outbox = task_dir / "outbox"
        if not outbox.is_dir():
            return self._send_json(200, {"files": []})
        files = []
        for f in sorted(outbox.rglob("*")):
            if f.is_file():
                rel = str(f.relative_to(outbox))
                st = f.stat()
                from datetime import datetime, timezone
                mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
                files.append({"name": rel, "size": st.st_size, "mtime": mtime})
        return self._send_json(200, {"files": files})

    def _handle_read_outbox_file(self, task_id: str, filename: str):
        task_dir = self.bridge_root / "tasks" / task_id
        filepath = task_dir / "outbox" / filename
        if not filepath.is_file():
            return self._send_json(404, {"error": f"File not found: {filename}"})
        try:
            content = filepath.read_text(encoding="utf-8")
            return self._send_json(200, {"name": filename, "content": content})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _handle_get_task_log(self, task_id: str):
        import subprocess
        from bridge.atomic import read_json_or_none
        from bridge.config import load_registry, get_project
        task_dir = self.bridge_root / "tasks" / task_id
        meta = read_json_or_none(task_dir / "META.json")
        if not meta:
            return self._send_json(404, {"error": f"Task {task_id} not found"})
        project_id = meta.get("projectId", "")
        try:
            registry = load_registry(self.bridge_root / "projects.json")
            project = get_project(registry, project_id)
        except Exception:
            project = None
        if not project:
            return self._send_json(200, {"startTime":0,"elapsed":0,"events":[],"toolCount":0,"reasoningCount":0})
        transport = getattr(project, "transport", "local")
        ssh_host = getattr(project, "ssh_host", None)
        remote_root = getattr(project, "remote_bridge_root", None) or getattr(project, "remote_workspace_root", None)

        if transport == "local" or not ssh_host:
            log_path = task_dir / "session.log"
            if not log_path.is_file():
                return self._send_json(200, {"startTime":0,"elapsed":0,"events":[],"toolCount":0,"reasoningCount":0})
            try:
                raw = log_path.read_text(encoding="utf-8", errors="replace")
                return self._send_json(200, _parse_task_session_log(raw))
            except Exception as e:
                return self._send_json(500, {"error": str(e)})
        else:
            if not remote_root:
                return self._send_json(200, {"startTime":0,"elapsed":0,"events":[],"toolCount":0,"reasoningCount":0})
            if transport == "remote-worktree":
                remote_task = f"{remote_root.rstrip('/')}/{task_id}"
            else:
                remote_task = f"{remote_root.rstrip('/')}/tasks/{task_id}"
            cmd = ["ssh", "-o", "BatchMode=yes", ssh_host,
                   f"tail -n 500 {remote_task}/session.log 2>/dev/null"]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                return self._send_json(200, _parse_task_session_log(r.stdout or ""))
            except Exception as e:
                return self._send_json(500, {"error": str(e)})

    def _handle_create_task(self):
        from bridge.application.task_service import create_task
        body = self._read_body()
        task_id = body.get("taskId") or body.get("task_id")
        project_id = body.get("projectId") or body.get("project_id")
        worker_id = body.get("workerId") or body.get("worker_id")
        role = body.get("role", "implement")
        task_file = body.get("taskFile") or body.get("task_file") or ""
        execution = body.get("execution") if isinstance(body.get("execution"), dict) else {}
        review = body.get("review") if isinstance(body.get("review"), dict) else {}

        if not task_id:
            return self._send_json(400, {"error": "taskId required"})
        if not project_id:
            return self._send_json(400, {"error": "projectId required"})

        try:
            meta = create_task(
                bridge_root=self.bridge_root,
                project_id=project_id,
                worker_id=worker_id,
                role=role,
                task_id=task_id,
                task_file=task_file,
                required_skills=body.get("requiredSkills", body.get("required_skills", [])),
                depends_on=body.get("dependsOn", body.get("depends_on", [])),
                priority=body.get("priority", 50),
                preferred_worker=execution.get(
                    "preferredWorker",
                    body.get("preferredWorker", body.get("preferred_worker")),
                ),
                excluded_workers=execution.get(
                    "excludedWorkers",
                    body.get("excludedWorkers", body.get("excluded_workers", [])),
                ),
                review_required=review.get(
                    "required",
                    body.get("reviewRequired", body.get("review_required", True)),
                ),
                independent_review=review.get(
                    "independentWorker",
                    body.get("independentReview", body.get("independent_review", True)),
                ),
                baseline=body.get("baseline"),
                workspace=execution.get(
                    "workspace",
                    body.get("workspace", body.get("workspace_mode")),
                ),
                target_minutes=execution.get(
                    "targetMinutes",
                    body.get("targetMinutes", body.get("target_minutes", 10)),
                ),
                soft_timeout_minutes=execution.get(
                    "softTimeoutMinutes",
                    body.get("softTimeoutMinutes", body.get("soft_timeout_minutes", 12)),
                ),
                hard_timeout_minutes=execution.get(
                    "hardTimeoutMinutes",
                    body.get(
                        "hardTimeoutMinutes",
                        body.get("timeoutMinutes", body.get("timeout_minutes", 15)),
                    ),
                ),
            )
            return self._send_json(201, meta)
        except ValueError as e:
            code = 409 if str(e).startswith("Task already exists:") else 400
            return self._send_json(code, {"error": str(e)})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _handle_cancel_task(self, task_id: str):
        from bridge.application.task_service import cancel_task
        from bridge.core.errors import TaskNotFoundError
        body = self._read_body()
        try:
            result = cancel_task(self.bridge_root, task_id, body.get("reason", ""))
            return self._send_json(200, result)
        except TaskNotFoundError as e:
            return self._send_json(404, {"error": str(e)})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _handle_retry_task(self, task_id: str):
        from bridge.core.state import get_state, set_state, FAILED, RETRYABLE, READY
        task_dir = self.bridge_root / "tasks" / task_id
        if not task_dir.exists():
            return self._send_json(404, {"error": f"Task {task_id} not found"})
        try:
            current = get_state(task_dir).get("state", "")
            if current not in (FAILED, RETRYABLE, "BLOCKED"):
                return self._send_json(400, {"error": f"Cannot retry from state {current}"})
            set_state(task_dir, READY)
            return self._send_json(200, {"taskId": task_id, "state": "READY"})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    # ── Review ──────────────────────────────────────────────────────────────

    def _handle_review_pass(self, task_id: str):
        from bridge.application.review_service import review_pass
        body = self._read_body()
        try:
            result = review_pass(
                self.bridge_root,
                task_id,
                reviewer_id=body.get("reviewerId", "api"),
                comment=body.get("comment", ""),
            )
            if not result.success:
                return self._send_json(409, {
                    "success": False,
                    "newState": result.new_state,
                    "error": result.error,
                })
            return self._send_json(200, {"success": True, "newState": result.new_state})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _handle_review_fix(self, task_id: str):
        from bridge.application.review_service import review_fix
        body = self._read_body()
        fix_file = body.get("fixFile") or body.get("fix_file") or ""
        comment = str(body.get("comment") or "").strip()
        try:
            if not fix_file:
                fix_path = self.bridge_root / "tasks" / task_id / "inbox" / "REVIEW_FIX.md"
                fix_path.parent.mkdir(parents=True, exist_ok=True)
                instruction = comment or "Please fix the issues."
                fix_path.write_text(f"# FIX\n\n{instruction}\n", encoding="utf-8")
                fix_file = str(fix_path)
            result = review_fix(
                self.bridge_root,
                task_id,
                fix_file,
                reviewer_id=body.get("reviewerId", "api"),
                comment=comment,
            )
            if not result.success:
                return self._send_json(409, {
                    "success": False,
                    "newState": result.new_state,
                    "error": result.error,
                })
            return self._send_json(200, {"success": True, "newState": result.new_state})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    # ── Integration ────────────────────────────────────────────────────────

    def _handle_integrate(self):
        from bridge.application.integration_service import integrate_approved_task
        body = self._read_body()
        task_id = body.get("taskId") or body.get("task_id")
        if not task_id:
            return self._send_json(400, {"error": "taskId required"})
        try:
            result = integrate_approved_task(self.bridge_root, task_id)
            return self._send_json(200, {
                "success": result.success,
                "taskId": result.task_id,
                "newState": result.new_state,
            })
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    # ── Metrics ─────────────────────────────────────────────────────────────

    def _handle_metrics(self):
        import dataclasses
        from bridge.telemetry import generate_report, collect_all_metrics
        try:
            tasks_dir = self.bridge_root / "tasks"
            report = generate_report(tasks_dir)
            data = dataclasses.asdict(report)
            metrics = collect_all_metrics(tasks_dir)
            data["workerPerformance"] = self._compute_worker_performance(metrics)
            data["generatedAt"] = time.time()
            return self._send_json(200, data)
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _compute_worker_performance(self, metrics):
        perf: dict = {}
        for m in metrics:
            wid = m.worker_id or "unknown"
            p = perf.setdefault(wid, {
                "workerId": wid, "tasks": 0, "completed": 0,
                "successCount": 0, "durations": [],
            })
            p["tasks"] += 1
            if m.is_terminal:
                p["completed"] += 1
            if m.status == "DONE":
                p["successCount"] += 1
            if m.execution_time_seconds is not None:
                p["durations"].append(m.execution_time_seconds)
        result = []
        for wid, p in sorted(perf.items()):
            durations = p.pop("durations")
            p["avgDurationSeconds"] = round(sum(durations) / len(durations), 3) if durations else None
            p["successRate"] = round(p["successCount"] / p["tasks"], 4) if p["tasks"] else 0.0
            result.append(p)
        return result

    def _handle_metrics_history(self, query: dict):
        from bridge.telemetry import collect_all_metrics
        try:
            metrics = collect_all_metrics(self.bridge_root / "tasks")
            try:
                limit = int(query.get("limit", ["50"])[0])
            except (ValueError, TypeError):
                limit = 50
            if limit < 0:
                limit = 50
            recent = metrics[-limit:] if limit else metrics
            entries = []
            for m in recent:
                entries.append({
                    "taskId": m.task_id,
                    "status": m.status,
                    "workerId": m.worker_id,
                    "role": m.role,
                    "attempt": m.attempt,
                    "createdAt": m.created_at,
                    "doneAt": m.done_at,
                    "executionTimeSeconds": m.execution_time_seconds,
                    "cycleTimeSeconds": m.total_cycle_time_seconds,
                    "queueTimeSeconds": m.queue_time_seconds,
                    "isFirstPass": m.is_first_pass,
                    "isTerminal": m.is_terminal,
                })
            cycle_times = [e["cycleTimeSeconds"] for e in entries if e["cycleTimeSeconds"] is not None]
            exec_times = [e["executionTimeSeconds"] for e in entries if e["executionTimeSeconds"] is not None]
            data = {
                "entries": entries,
                "count": len(entries),
                "avgCycleTimeSeconds": round(sum(cycle_times) / len(cycle_times), 3) if cycle_times else None,
                "avgExecutionTimeSeconds": round(sum(exec_times) / len(exec_times), 3) if exec_times else None,
                "generatedAt": time.time(),
            }
            return self._send_json(200, data)
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _handle_cost(self):
        from bridge.telemetry import collect_all_metrics
        from bridge.cost import token_total
        from bridge.atomic import read_json_or_none
        try:
            tasks_dir = self.bridge_root / "tasks"
            metrics = collect_all_metrics(tasks_dir)
            rates = self._load_cost_rates()
            rate_per_mtok = float(rates.get("ratePerMTokens", 0.0) or 0.0)
            role_rates = rates.get("byRole", {}) or {}

            by_project: dict = {}
            by_worker: dict = {}
            by_role: dict = {}
            total_tokens = 0
            total_cost = 0.0

            for m in metrics:
                meta = read_json_or_none(tasks_dir / m.task_id / "META.json") or {}
                project_id = meta.get("projectId", "unknown")
                worker_id = m.worker_id or "unknown"
                role = m.role or "unknown"
                tokens = token_total(m.tokens)
                total_tokens += tokens
                rate = float(role_rates.get(role, rate_per_mtok) or 0.0)
                cost = tokens / 1_000_000.0 * rate
                total_cost += cost

                for key, bucket in ((project_id, by_project), (worker_id, by_worker), (role, by_role)):
                    b = bucket.setdefault(key, {"tasks": 0, "tokens": 0, "estimatedCost": 0.0})
                    b["tasks"] += 1
                    b["tokens"] += tokens
                    b["estimatedCost"] += cost

            def _to_list(d):
                return [{"key": k, "tasks": v["tasks"], "tokens": v["tokens"],
                         "estimatedCost": round(v["estimatedCost"], 6)}
                        for k, v in sorted(d.items())]

            data = {
                "byProject": _to_list(by_project),
                "byWorker": _to_list(by_worker),
                "byRole": _to_list(by_role),
                "totalTasks": len(metrics),
                "totalTokens": total_tokens,
                "totalEstimatedCost": round(total_cost, 6),
                "costRates": rates,
                "hasCostData": total_tokens > 0,
                "generatedAt": time.time(),
            }
            return self._send_json(200, data)
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _load_cost_rates(self) -> dict:
        cf = self.bridge_root / "cost_rates.json"
        if cf.exists():
            try:
                data = json.loads(cf.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {"ratePerMTokens": 0.0, "byRole": {}}

    # ── Event Stream (SSE) ──────────────────────────────────────────────────

    def _handle_event_stream(self, query: dict):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        from bridge.core.events import EventStore
        events_dir = self.bridge_root / "events"
        store = EventStore(events_dir)

        last_count = 0
        keepalive = 0
        try:
            while True:
                recent = store.recent(100)
                if len(recent) > last_count:
                    for evt in recent[last_count:]:
                        self._send_sse(evt.type, {
                            "eventId": evt.event_id,
                            "taskId": evt.task_id,
                            "payload": evt.payload,
                        })
                    last_count = len(recent)
                keepalive += 1
                if keepalive % 10 == 0:
                    self._send_sse("keepalive", {"timestamp": time.time()})
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            pass


def create_handler(bridge_root: Path):
    """Create a handler class bound to a specific bridge_root."""
    class BoundHandler(BridgeAPIHandler):
        pass
    BoundHandler.bridge_root = Path(bridge_root)
    return BoundHandler


class BridgeAPIServer:
    """HTTP API server for CodeartsBridge."""

    def __init__(self, bridge_root: str | Path, host: str = "0.0.0.0", port: int = 8080):
        self.bridge_root = Path(bridge_root)
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        handler = create_handler(self.bridge_root)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("API server listening on %s:%d", self.host, self.port)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def url(self, path: str = "") -> str:
        return f"http://{self.host}:{self.port}{path}"