"""Agent transport: Bridge communicates with Worker via HTTP Agent API."""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from .base import TransportBase, TransportResult


class AgentTransport(TransportBase):
    """Run tasks via Bridge Worker Runtime Agent HTTP API."""

    def run(
        self,
        project: Any,
        worker: Any,
        task_dir: str | Path,
        task_id: str,
        mode: str = "auto",
        timeout_seconds: int = 900,
        soft_timeout_seconds: int = 0,
        session_id: str | None = None,
        attempt: int = 0,
        baseline: str | None = None,
        quiet: bool = False,
        model: str | None = None,
    ) -> TransportResult:
        task_dir = Path(task_dir)

        endpoint = getattr(worker, "endpoint", None) or getattr(worker, "agent_endpoint", None)
        if not endpoint:
            return TransportResult(exit_code=-1, stderr="Worker missing agent endpoint")
        endpoint = endpoint.rstrip("/")

        token = getattr(worker, "agent_token", None) or ""
        if not token:
            import os
            token_env = getattr(worker, "agent_token_env", None)
            if token_env:
                token = os.environ.get(token_env, "")

        prompt = self._build_prompt(task_dir, project)
        project_root = getattr(project, "project_root", "")
        cli_path = getattr(worker, "cli_path", "codearts") or "codearts"

        job_request = {
            "taskId": task_id,
            "attempt": attempt + 1,
            "projectRoot": project_root,
            "cliPath": cli_path,
            "model": model or "",
            "mode": mode,
            "prompt": prompt,
            "softTimeoutSeconds": soft_timeout_seconds or int(timeout_seconds * 0.8),
            "hardTimeoutSeconds": timeout_seconds,
            "sessionId": session_id,
        }

        try:
            resp = self._post(f"{endpoint}/v1/jobs", token, job_request)
        except Exception as e:
            return TransportResult(exit_code=-1, stderr=str(e))

        if resp.get("error"):
            return TransportResult(exit_code=-1, stderr=resp["error"])

        job_id = resp.get("jobId", "")
        if not job_id:
            return TransportResult(exit_code=-1, stderr="No jobId returned")

        self._save_inflight(task_dir, job_id, endpoint, token)
        result = self._poll_job(endpoint, token, job_id, timeout_seconds)
        self._fetch_artifacts(endpoint, token, job_id, task_dir)
        self._clear_inflight(task_dir)
        return result

    def _build_prompt(self, task_dir: Path, project: Any) -> str:
        from ..codearts import build_worker_core_prompt, get_worker_local_access_directive
        instructions = self._get_instructions(task_dir)
        worker_contract = task_dir.parent.parent / "protocol" / "WORKER.md"
        meta_path = task_dir / "META.json"
        outbox_path = task_dir / "outbox"
        project_path = getattr(project, "project_root", "")
        directive = get_worker_local_access_directive(project_path)
        return build_worker_core_prompt(
            worker_contract=str(worker_contract),
            meta_path=str(meta_path),
            instructions=instructions,
            outbox_path=str(outbox_path),
            project_path=project_path,
            remote_directive=directive,
        )

    def _get_instructions(self, task_dir: Path) -> list[str]:
        inbox = task_dir / "inbox"
        files = sorted(inbox.glob("*.md"))
        return [str(f) for f in files]

    def _post(self, url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get(self, url: str, token: str) -> dict[str, Any]:
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _poll_job(self, endpoint: str, token: str, job_id: str, timeout: int) -> TransportResult:
        deadline = time.time() + timeout + 60
        cursor = 0
        last_state = ""
        session_mode = "new"

        while time.time() < deadline:
            try:
                resp = self._get(f"{endpoint}/v1/jobs/{job_id}", token)
            except Exception as e:
                time.sleep(2)
                continue

            state = resp.get("state", "")
            if state != last_state:
                last_state = state

            if state in ("COMPLETED",):
                return TransportResult(
                    exit_code=resp.get("exitCode", 0),
                    stdout="",
                    stderr="",
                    session_mode=session_mode,
                )
            if state == "COMPLETED_WITH_TIMEOUT":
                return TransportResult(
                    exit_code=resp.get("exitCode", -1),
                    stdout="",
                    stderr="",
                    timed_out=True,
                    session_mode=session_mode,
                )
            if state == "TIMED_OUT":
                return TransportResult(
                    exit_code=-1,
                    stdout="",
                    stderr="Hard timeout",
                    timed_out=True,
                    assistance_requested=True,
                    session_mode=session_mode,
                )
            if state == "ASSISTANCE_REQUIRED":
                return TransportResult(
                    exit_code=resp.get("exitCode", -1),
                    stdout="",
                    stderr="Assistance required",
                    assistance_requested=True,
                    session_mode=session_mode,
                )
            if state == "CANCELLED":
                return TransportResult(
                    exit_code=-1,
                    stdout="",
                    stderr="Cancelled",
                    cancelled=True,
                    session_mode=session_mode,
                )

            try:
                events_resp = self._get(f"{endpoint}/v1/jobs/{job_id}/events?cursor={cursor}", token)
                cursor = events_resp.get("cursor", cursor)
            except Exception:
                pass

            time.sleep(2)

        return TransportResult(
            exit_code=-1,
            stdout="",
            stderr="Polling timeout",
            timed_out=True,
            session_mode=session_mode,
        )

    def _fetch_artifacts(self, endpoint: str, token: str, job_id: str, task_dir: Path) -> None:
        """Download all artifacts from Agent and write to local outbox."""
        try:
            resp = self._get(f"{endpoint}/v1/jobs/{job_id}/artifacts", token)
        except Exception:
            return

        local_outbox = task_dir / "outbox"
        local_outbox.mkdir(parents=True, exist_ok=True)

        local_salvage = task_dir / "salvage"
        for category in ("outbox", "salvage", "files"):
            items = resp.get(category, [])
            for item in items:
                name = item.get("name", "")
                if not name:
                    continue
                try:
                    file_url = f"{endpoint}/v1/jobs/{job_id}/files/{category}/{name}"
                    content = self._get_raw(file_url, token)
                    if content:
                        if category == "salvage":
                            local_salvage.mkdir(parents=True, exist_ok=True)
                            (local_salvage / name).write_bytes(content)
                        elif category == "files":
                            (task_dir / name).write_bytes(content)
                        else:
                            (local_outbox / name).write_bytes(content)
                except Exception:
                    pass

    def _get_raw(self, url: str, token: str) -> bytes:
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    def _save_inflight(self, task_dir: Path, job_id: str, endpoint: str, token: str) -> None:
        """Persist job_id so Bridge can resume polling after restart."""
        inflight = task_dir / "inflight.json"
        try:
            inflight.write_text(json.dumps({
                "jobId": job_id,
                "endpoint": endpoint,
                "token": token,
            }), encoding="utf-8")
        except Exception:
            pass

    def _clear_inflight(self, task_dir: Path) -> None:
        """Remove inflight marker after job completes."""
        inflight = task_dir / "inflight.json"
        if inflight.exists():
            try:
                inflight.unlink()
            except Exception:
                pass

    def resume_inflight(self, task_dir: str | Path, timeout_seconds: int = 900) -> TransportResult | None:
        """Resume polling an inflight Agent job after Bridge restart.

        Returns None if no inflight job exists, or TransportResult if
        the job was found and polled to completion.
        """
        task_dir = Path(task_dir)
        inflight = task_dir / "inflight.json"
        if not inflight.exists():
            return None
        try:
            data = json.loads(inflight.read_text(encoding="utf-8"))
        except Exception:
            return None
        job_id = data.get("jobId", "")
        endpoint = data.get("endpoint", "")
        token = data.get("token", "")
        if not job_id or not endpoint:
            return None
        result = self._poll_job(endpoint, token, job_id, timeout_seconds)
        self._fetch_artifacts(endpoint, token, job_id, task_dir)
        self._clear_inflight(task_dir)
        return result