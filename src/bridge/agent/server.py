"""HTTP API server for Bridge Worker Runtime."""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from .auth import check_auth, AuthError, extract_bearer
from .config import AgentConfig
from .models import JobInfo, JobRequest, JobState, LogEvent
from .store import JobStore
from .runner import Runner
from .watchdog import Watchdog
from .recovery import Recovery
from .artifacts import collect_artifacts


class AgentServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        data_root: str | Path = "~/.codex-glm-bridge/agent",
        config: AgentConfig | None = None,
        token: str | None = None,
    ):
        self.host = host
        self.port = port
        self.data_root = Path(os.path.expanduser(str(data_root)))
        self.data_root.mkdir(parents=True, exist_ok=True)

        self.config = config or AgentConfig()
        self.config.hostname = socket.gethostname()

        self.token = token or os.environ.get("BRIDGE_AGENT_TOKEN", "")


        self.store = JobStore(self.data_root)
        self.runner = Runner(self.store)
        self.watchdog = Watchdog(self.store, self.runner)
        self.recovery = Recovery(self.store, self.runner)

        self._server: ThreadingHTTPServer | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        recovery = self.recovery.reconcile()
        if recovery:
            for job in recovery:
                pass

        handler = _make_handler(self)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.daemon_threads = True

        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

        self._server.serve_forever()

    def stop(self) -> None:
        self._stop.set()

        # Do not leave CodeArts children behind when the Agent is restarted or
        # redeployed. They run in their own process group, so without explicit
        # cleanup they can become PPID=1 orphans and keep shared CLI state busy.
        for job in self.store.list_active_jobs():
            try:
                self.runner.terminate(job, grace_seconds=2)
                job.state = JobState.CANCELLED.value
                job.lastEventAt = time.time()
                self.store.save_job(job)
                self.runner.release(job.jobId)
            except Exception:
                pass

        if self._server:
            self._server.shutdown()

    def _watchdog_loop(self) -> None:
        while not self._stop.is_set():
            for job in self.store.list_active_jobs():
                self.watchdog.check_timeouts(job)
                self._check_completion(job)
            time.sleep(2)

    def _check_completion(self, job: JobInfo) -> None:
        if job.state not in (JobState.RUNNING.value, JobState.SOFT_LIMIT.value):
            return
        if not self.runner.check_process(job):
            exit_code = self.runner.get_exit_code(job)
            if exit_code is not None:
                self.runner.wait_for_streams(job.jobId, timeout=1.0)
                job.state = JobState.COMPLETED.value if exit_code == 0 else JobState.ASSISTANCE_REQUIRED.value
                job.exitCode = exit_code
                job.lastEventAt = time.time()
                self.store.save_job(job)

                # Archive project-local outbox to agent artifacts, then clean up.
                from .runner import archive_project_outbox
                agent_outbox = self.store.job_dir(job.jobId) / "artifacts" / "outbox"
                agent_outbox.mkdir(parents=True, exist_ok=True)
                archived = archive_project_outbox(job.projectRoot, job.jobId, agent_outbox)
                if archived:
                    self.store.append_event(job.jobId, LogEvent(
                        id=f"evt-{time.time_ns()}",
                        time=time.time(),
                        type="archived",
                        text=f"Archived {archived} outbox file(s) from project-local",
                        status="completed",
                    ))

                self.store.append_event(job.jobId, LogEvent(
                    id=f"evt-{time.time_ns()}",
                    time=time.time(),
                    type="completed",
                    text=f"Process exited with code {exit_code}",
                    status="completed" if exit_code == 0 else "failed",
                ))
                self.runner.release(job.jobId)

    def handle_health(self) -> tuple[int, dict[str, Any]]:
        import shutil
        cli_path = shutil.which("codearts") or ""
        return (200, {
            "ok": True,
            "agentVersion": self.config.agent_version,
            "hostname": self.config.hostname,
            "activeJobs": len(self.store.list_active_jobs()),
            "capacity": self.config.capacity,
            "codearts": {
                "available": True,
                "path": cli_path,
            },
        })

    def handle_create_job(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        active = self.store.list_active_jobs()
        if len(active) >= self.config.capacity:
            return (429, {"error": "At capacity", "activeJobs": len(active)})

        req = JobRequest.from_dict(body)

        job_id = f"job-{uuid.uuid4().hex[:12]}"
        job = JobInfo(
            jobId=job_id,
            taskId=req.taskId,
            state=JobState.STARTING.value,
            attempt=req.attempt,
            projectRoot=req.projectRoot,
            cliPath=req.cliPath,
            model=req.model,
            mode=req.mode,
            softTimeoutSeconds=req.softTimeoutSeconds,
            hardTimeoutSeconds=req.hardTimeoutSeconds,
            sessionId=req.sessionId,
            prompt=req.prompt,
        )
        self.store.save_job(job)

        try:
            pid, pgid = self.runner.start(job)
        except Exception as e:
            job.state = JobState.ASSISTANCE_REQUIRED.value
            self.store.save_job(job)
            return (500, {"error": str(e), "jobId": job_id})

        return (200, {"jobId": job_id, "state": job.state})

    def handle_get_job(self, job_id: str) -> tuple[int, dict[str, Any]]:
        job = self.store.load_job(job_id)
        if not job:
            return (404, {"error": "Job not found"})
        job.update_elapsed()
        return (200, job.to_dict())

    def handle_events(self, job_id: str, cursor: int = 0) -> tuple[int, dict[str, Any]]:
        new_cursor, events = self.store.read_events(job_id, cursor)
        return (200, {
            "cursor": new_cursor,
            "events": [e.to_dict() for e in events],
        })

    def handle_cancel(self, job_id: str) -> tuple[int, dict[str, Any]]:
        job = self.store.load_job(job_id)
        if not job:
            return (404, {"error": "Job not found"})
        if JobState(job.state).is_terminal:
            return (409, {"error": "Job already terminal", "state": job.state})

        self.runner.terminate(job)
        job.state = JobState.CANCELLED.value
        job.lastEventAt = time.time()
        self.store.save_job(job)
        self.runner.release(job.jobId)
        return (200, {"jobId": job_id, "state": job.state})

    def handle_artifacts(self, job_id: str) -> tuple[int, dict[str, Any]]:
        job = self.store.load_job(job_id)
        if not job:
            return (404, {"error": "Job not found"})
        job_dir = self.store.job_dir(job_id)
        return (200, collect_artifacts(job_dir))

    def handle_file(
        self, job_id: str, category: str, name: str
    ) -> tuple[int, bytes, str]:
        """Serve a raw file from a job's artifacts directory.

        Returns (status_code, content_bytes, content_type).
        """
        job = self.store.load_job(job_id)
        if not job:
            return (404, b'{"error":"Job not found"}', "application/json")
        job_dir = self.store.job_dir(job_id)

        if category == "outbox":
            path = job_dir / "artifacts" / "outbox" / name
        elif category == "salvage":
            path = job_dir / "artifacts" / "runtime-salvage" / name
        elif category == "files":
            path = job_dir / name
        else:
            return (404, b'{"error":"Unknown category"}', "application/json")

        if not path.exists() or not path.is_file():
            return (404, b'{"error":"File not found"}', "application/json")

        return (200, path.read_bytes(), "application/octet-stream")


def _make_handler(server: AgentServer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send_json(self, code: int, data: dict[str, Any]):
            body = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _check_auth(self) -> bool:
            if not server.token:
                return True
            try:
                headers = {k: v for k, v in self.headers.items()}
                check_auth(headers, server.token)
                return True
            except AuthError as e:
                self._send_json(401, {"error": str(e)})
                return False

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/v1/health":
                code, data = server.handle_health()
                self._send_json(code, data)
                return

            if not self._check_auth():
                return

            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "v1" and parts[1] == "jobs":
                job_id = parts[2]
                if len(parts) == 3:
                    code, data = server.handle_get_job(job_id)
                    self._send_json(code, data)
                elif len(parts) == 4 and parts[3] == "events":
                    qs = parse_qs(parsed.query)
                    cursor = int(qs.get("cursor", ["0"])[0])
                    code, data = server.handle_events(job_id, cursor)
                    self._send_json(code, data)
                elif len(parts) == 4 and parts[3] == "artifacts":
                    code, data = server.handle_artifacts(job_id)
                    self._send_json(code, data)
                elif len(parts) == 6 and parts[3] == "files":
                    category = parts[4]
                    name = parts[5]
                    code, content, ct = server.handle_file(job_id, category, name)
                    self.send_response(code)
                    self.send_header("Content-Type", ct)
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self._send_json(404, {"error": "Not found"})
            else:
                self._send_json(404, {"error": "Not found"})

        def do_POST(self):
            if not self._check_auth():
                return

            parsed = urlparse(self.path)
            path = parsed.path
            parts = path.strip("/").split("/")

            if len(parts) == 2 and parts[0] == "v1" and parts[1] == "jobs":
                body = self._read_body()
                code, data = server.handle_create_job(body)
                self._send_json(code, data)
            elif len(parts) == 4 and parts[0] == "v1" and parts[1] == "jobs" and parts[3] == "cancel":
                job_id = parts[2]
                code, data = server.handle_cancel(job_id)
                self._send_json(code, data)
            else:
                self._send_json(404, {"error": "Not found"})

    return Handler