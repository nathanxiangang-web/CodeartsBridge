"""Local process runner — argv execution behind a real PTY."""
from __future__ import annotations

import json as _json
import os
import pty
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .models import JobInfo, JobState, LogEvent
from .store import JobStore


_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\r|\x00')


def _parse_codearts_line(line: str) -> tuple[str, str] | None:
    """Parse one codearts JSON event line into (type, text)."""
    try:
        obj = _json.loads(line)
    except (_json.JSONDecodeError, ValueError):
        return None
    if not obj or not isinstance(obj, dict):
        return None

    ptype = obj.get("type", "")
    part = obj.get("part", {})
    if not isinstance(part, dict):
        part = {}

    if ptype == "reasoning":
        text = part.get("text", "")
        if text:
            return ("reasoning", str(text)[:200])
    elif ptype == "tool_use":
        tool = part.get("tool", "")
        state = part.get("state", {}) or {}
        inp = state.get("input", {}) or {}
        summary = str(tool)
        if tool == "read" and inp.get("filePath"):
            summary += " " + str(inp["filePath"]).split("/")[-1]
        elif tool == "write" and inp.get("filePath"):
            summary += " " + str(inp["filePath"]).split("/")[-1]
        elif tool == "bash" and inp.get("command"):
            summary += " " + str(inp["command"])[:60]
        elif tool == "edit" and inp.get("filePath"):
            summary += " " + str(inp["filePath"]).split("/")[-1]
        return ("tool", summary)
    elif ptype == "step_start":
        return ("step", "开始执行")

    return None


class Runner:
    def __init__(self, store: JobStore):
        self.store = store
        self._streamers: dict[str, threading.Thread] = {}

    def start(self, job: JobInfo) -> tuple[int, int]:
        cli = job.cliPath
        args = self._build_args(job)
        job_dir = self.store.job_dir(job.jobId)
        session_log_path = job_dir / "session.log"
        outbox_path = job_dir / "artifacts" / "outbox"
        outbox_path.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        env["CODEARTS_OUTBOX"] = str(outbox_path)

        master_fd, slave_fd = pty.openpty()
        proc = subprocess.Popen(
            [cli] + args,
            cwd=job.projectRoot,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            env=env,
        )
        os.close(slave_fd)

        pid = proc.pid
        pgid = os.getpgid(pid)
        self.store.save_process_info(job.jobId, pid, pgid)

        job.pid = pid
        job.state = JobState.RUNNING.value
        job.startedAt = time.time()
        job.lastEventAt = job.startedAt
        self.store.save_job(job)

        self.store.append_event(job.jobId, LogEvent(
            id=f"evt-{int(time.time()*1000)}",
            time=time.time(),
            type="started",
            text=f"Process started: pid={pid}",
            status="running",
        ))

        t = threading.Thread(
            target=self._read_master,
            args=(job.jobId, master_fd, session_log_path, proc),
            daemon=True,
        )
        self._streamers[job.jobId] = t
        t.start()

        return pid, pgid

    def _read_master(self, job_id: str, master_fd: int, session_log_path: Path, proc: subprocess.Popen) -> None:
        leftover = b""
        with open(session_log_path, "wb") as log_f:
            while True:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    data = b""

                if data:
                    log_f.write(data)
                    log_f.flush()
                    leftover += data
                    while b"\n" in leftover:
                        raw_line, leftover = leftover.split(b"\n", 1)
                        self._ingest_line(job_id, raw_line)
                else:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)

        if leftover:
            self._ingest_line(job_id, leftover)

        try:
            os.close(master_fd)
        except OSError:
            pass
        self._streamers.pop(job_id, None)

    def _ingest_line(self, job_id: str, raw_line: bytes) -> None:
        text = raw_line.decode("utf-8", errors="replace")
        clean = _ANSI_RE.sub('', text).strip()
        if not clean:
            return
        parsed = _parse_codearts_line(clean)
        if parsed:
            self.store.append_event(job_id, LogEvent(
                id=f"evt-{int(time.time()*1000)}",
                time=time.time(),
                type=parsed[0],
                text=parsed[1],
                status="running",
            ))

    def _build_args(self, job: JobInfo) -> list[str]:
        args = ["run", job.prompt, "--format", "json", "--thinking", "--auto"]
        if job.sessionId:
            args += ["--session", job.sessionId]
        if job.model:
            args += ["-m", job.model]
        return args

    def check_process(self, job: JobInfo) -> bool:
        if job.pid is None:
            return False
        try:
            _, status = os.waitpid(job.pid, os.WNOHANG)
            if status != 0:
                return False
            return True
        except ChildProcessError:
            return False

    def get_exit_code(self, job: JobInfo) -> int | None:
        if job.pid is None:
            return None
        try:
            _, status = os.waitpid(job.pid, os.WNOHANG)
            if status == 0:
                return None
            if os.WIFEXITED(status):
                return os.WEXITSTATUS(status)
            if os.WIFSIGNALED(status):
                return -os.WTERMSIG(status)
            return None
        except ChildProcessError:
            return None

    def terminate(self, job: JobInfo, grace_seconds: int = 5) -> None:
        proc_info = self.store.load_process_info(job.jobId)
        if not proc_info:
            return
        pgid = proc_info.get("pgid")
        if pgid is None:
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return

        deadline = time.time() + grace_seconds
        while time.time() < deadline:
            if not self.check_process(job):
                break
            time.sleep(0.5)

        if self.check_process(job):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        self.store.append_event(job.jobId, LogEvent(
            id=f"evt-{int(time.time()*1000)}",
            time=time.time(),
            type="cancelled",
            text="Process terminated",
            status="cancelled",
        ))