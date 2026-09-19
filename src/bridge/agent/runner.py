"""Local process runner with live CodeArts JSON streaming.

CodeArts `run --format json` is a non-interactive machine-output mode.  Keep
stdout/stderr as pipes: forcing a PTY changes the child's terminal semantics
and, with current CodeArts CLI builds, can leave the process busy while no
JSON reaches Bridge.
"""
from __future__ import annotations

import json as _json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import BinaryIO

from .models import JobInfo, JobState, LogEvent
from .store import JobStore


_ANSI_RE = re.compile(
    r"(?:\x1B\][^\x07]*(?:\x07|\x1B\\))|"
    r"(?:\x1B\[[0-?]*[ -/]*[@-~])|\r|\x00"
)


def _event_id() -> str:
    """Return a collision-resistant event id for high-rate UI streams."""
    return f"evt-{time.time_ns()}"


def _resolve_cli_path(cli: str) -> str:
    """Resolve CodeArts to the official per-user install before PATH wrappers."""
    if cli != "codearts":
        return cli

    candidates = (
        # Prefer the resolved executable used by this host's ~/.local/bin
        # symlink. The installers/codearts entry is a shell launcher and is
        # intentionally only a fallback.
        Path.home() / ".codeartsdoer" / "installers" / "bin" / "codearts",
        Path.home() / ".local" / "bin" / "codearts",
        Path.home() / ".codeartsdoer" / "installers" / "codearts",
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    return shutil.which("codearts") or cli


def _probe_cli(cli: str, timeout_seconds: float = 5.0) -> str:
    """Fail fast when the CodeArts launcher itself is hung or broken."""
    proc = subprocess.Popen(
        [cli, "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.communicate()
        raise RuntimeError(
            f"CodeArts CLI unhealthy: '{cli} --version' timed out after "
            f"{timeout_seconds:g}s"
        )

    if proc.returncode != 0:
        detail = (stderr or stdout or "").strip()[:300]
        raise RuntimeError(
            f"CodeArts CLI unhealthy: '{cli} --version' exited "
            f"{proc.returncode}: {detail}"
        )

    return (stdout or stderr or "").strip()


def _parse_codearts_line(line: str) -> tuple[str, str] | None:
    """Parse one CodeArts JSON event line into a compact UI event."""
    try:
        obj = _json.loads(line)
    except (_json.JSONDecodeError, ValueError):
        return None
    if not obj or not isinstance(obj, dict):
        return None

    ptype = str(obj.get("type", ""))
    part = obj.get("part", {})
    if not isinstance(part, dict):
        part = {}

    if ptype == "reasoning":
        text = part.get("text") or obj.get("text") or ""
        if text:
            return ("reasoning", str(text)[:200])

    if ptype == "tool_use":
        tool = part.get("tool") or obj.get("tool") or ""
        state = part.get("state", {}) or {}
        if not isinstance(state, dict):
            state = {}
        inp = state.get("input", {}) or {}
        if not isinstance(inp, dict):
            inp = {}

        summary = str(tool or "tool")
        file_path = inp.get("filePath") or inp.get("path")
        if tool in {"read", "write", "edit"} and file_path:
            summary += " " + str(file_path).split("/")[-1]
        elif tool == "bash" and inp.get("command"):
            summary += " " + str(inp["command"])[:60]
        return ("tool", summary)

    if ptype == "step_start":
        return ("step", "开始执行")

    return None


class Runner:
    def __init__(self, store: JobStore):
        self.store = store
        self._processes: dict[str, subprocess.Popen] = {}
        self._streamers: dict[str, list[threading.Thread]] = {}

    def start(self, job: JobInfo) -> tuple[int, int]:
        cli = _resolve_cli_path(job.cliPath)
        _probe_cli(cli)
        args = self._build_args(job)
        job_dir = self.store.job_dir(job.jobId)
        session_log_path = job_dir / "session.log"
        stderr_path = job_dir / "stderr.log"
        outbox_path = job_dir / "artifacts" / "outbox"
        outbox_path.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        env["CODEARTS_OUTBOX"] = str(outbox_path)

        # IMPORTANT: do not wrap this in pty.openpty() or util-linux script.
        # `codearts run --format json` is already non-interactive. A PTY makes
        # CodeArts select terminal-oriented behaviour and has been observed to
        # run at high CPU while emitting zero bytes to Bridge.
        proc = subprocess.Popen(
            [cli] + args,
            cwd=job.projectRoot,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=env,
            bufsize=0,
        )
        self._processes[job.jobId] = proc

        pid = proc.pid
        pgid = os.getpgid(pid)
        self.store.save_process_info(job.jobId, pid, pgid)

        job.pid = pid
        job.state = JobState.RUNNING.value
        job.startedAt = time.time()
        job.lastEventAt = job.startedAt
        self.store.save_job(job)

        self.store.append_event(job.jobId, LogEvent(
            id=_event_id(),
            time=time.time(),
            type="started",
            text=f"Process started: pid={pid} (json-pipe, cli={cli})",
            status="running",
        ))

        stdout_thread = threading.Thread(
            target=self._read_stream,
            args=(job.jobId, proc.stdout, session_log_path),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._read_stream,
            args=(job.jobId, proc.stderr, stderr_path),
            daemon=True,
        )
        self._streamers[job.jobId] = [stdout_thread, stderr_thread]
        stdout_thread.start()
        stderr_thread.start()

        return pid, pgid

    def _read_stream(
        self,
        job_id: str,
        stream: BinaryIO | None,
        log_path: Path,
    ) -> None:
        """Persist one child stream and emit any JSON events line-by-line."""
        if stream is None:
            return

        leftover = b""
        try:
            with open(log_path, "wb") as log_f:
                while True:
                    data = os.read(stream.fileno(), 4096)
                    if not data:
                        break
                    log_f.write(data)
                    log_f.flush()
                    leftover += data
                    while b"\n" in leftover:
                        raw_line, leftover = leftover.split(b"\n", 1)
                        self._ingest_line(job_id, raw_line)

                if leftover:
                    self._ingest_line(job_id, leftover)
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _ingest_line(self, job_id: str, raw_line: bytes) -> None:
        text = raw_line.decode("utf-8", errors="replace")
        clean = _ANSI_RE.sub("", text).strip()
        if not clean:
            return

        parsed = _parse_codearts_line(clean)
        if not parsed:
            return

        now = time.time()
        self.store.append_event(job_id, LogEvent(
            id=_event_id(),
            time=now,
            type=parsed[0],
            text=parsed[1],
            status="running",
        ))

        # Keep job liveness aligned with the actual CodeArts stream. This is
        # intentionally best-effort so event delivery is never blocked by a
        # state-file update failure.
        try:
            job = self.store.load_job(job_id)
            if job is not None:
                job.lastEventAt = now
                self.store.save_job(job)
        except Exception:
            pass

    def _build_args(self, job: JobInfo) -> list[str]:
        args = ["run", job.prompt, "--format", "json", "--thinking"]
        if job.sessionId:
            args += ["--session", job.sessionId]
        elif job.taskId:
            args += ["--title", job.taskId]
        if job.model:
            args += ["-m", job.model]
        if job.mode == "auto":
            args.append("--auto")
        elif job.mode == "sandbox":
            args.append("--sandbox")
        return args

    def check_process(self, job: JobInfo) -> bool:
        proc = self._processes.get(job.jobId)
        if proc is not None:
            return proc.poll() is None

        # Recovery path: after an Agent restart the Popen object no longer
        # exists, but the persisted PID can still tell us whether it lives.
        if job.pid is None:
            return False
        try:
            os.kill(job.pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def get_exit_code(self, job: JobInfo) -> int | None:
        proc = self._processes.get(job.jobId)
        if proc is None:
            return None
        return proc.poll()

    def wait_for_streams(self, job_id: str, timeout: float = 1.0) -> None:
        """Give stdout/stderr readers a short chance to drain final output."""
        threads = list(self._streamers.get(job_id, []))
        deadline = time.monotonic() + timeout
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

    def release(self, job_id: str) -> None:
        """Drop completed in-memory process bookkeeping."""
        self._processes.pop(job_id, None)
        self._streamers.pop(job_id, None)

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
            time.sleep(0.2)

        if self.check_process(job):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        self.store.append_event(job.jobId, LogEvent(
            id=_event_id(),
            time=time.time(),
            type="cancelled",
            text="Process terminated",
            status="cancelled",
        ))
