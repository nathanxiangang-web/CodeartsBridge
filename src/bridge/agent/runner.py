"""Local process runner — argv execution, no shell=True."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from .models import JobInfo, JobState, LogEvent
from .store import JobStore


class Runner:
    def __init__(self, store: JobStore):
        self.store = store

    def start(self, job: JobInfo) -> tuple[int, int]:
        cli = job.cliPath
        args = self._build_args(job)
        stdout_path = self.store.job_dir(job.jobId) / "stdout.jsonl"
        stderr_path = self.store.job_dir(job.jobId) / "stderr.log"

        with open(stdout_path, "w", encoding="utf-8") as stdout_file:
            with open(stderr_path, "w", encoding="utf-8") as stderr_file:
                proc = subprocess.Popen(
                    [cli] + args,
                    cwd=job.projectRoot,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    start_new_session=True,
                )

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

        return pid, pgid

    def _build_args(self, job: JobInfo) -> list[str]:
        args = ["run", "--model", job.model or "huaweicloud-maas/GLM-5.2"]
        if job.mode and job.mode != "auto":
            args += ["--mode", job.mode]
        if job.sessionId:
            args += ["--session", job.sessionId]
        args += ["--", job.prompt]
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