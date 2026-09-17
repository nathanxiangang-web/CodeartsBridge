# AI生成
"""Process management for runtime supervisor.

Wraps subprocess.Popen with structured stdout/stderr capture,
process group control, and graceful termination.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO


@dataclass
class ProcessResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False
    duration_seconds: float = 0.0


class ManagedProcess:
    """A managed subprocess with process group control."""

    def __init__(
        self,
        command: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        stdout_file: Path | None = None,
        stderr_file: Path | None = None,
    ):
        self.command = command
        self.cwd = cwd
        self.env = env or {}
        self.stdout_file = stdout_file
        self.stderr_file = stderr_file
        self._proc: subprocess.Popen | None = None
        self._start_time: float = 0.0

    def start(self) -> None:
        """Start the process in a new process group."""
        import time

        full_env = dict(os.environ)
        full_env.update(self.env)

        stdout: IO = subprocess.PIPE
        stderr: IO = subprocess.PIPE

        if self.stdout_file:
            self.stdout_file.parent.mkdir(parents=True, exist_ok=True)
            stdout = open(self.stdout_file, "w", encoding="utf-8")
        if self.stderr_file:
            self.stderr_file.parent.mkdir(parents=True, exist_ok=True)
            stderr = open(self.stderr_file, "w", encoding="utf-8")

        self._proc = subprocess.Popen(
            self.command,
            cwd=str(self.cwd) if self.cwd else None,
            env=full_env,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,  # New process group (POSIX)
        )
        self._start_time = time.time()

    @property
    def pid(self) -> int | None:
        if self._proc is None:
            return None
        return self._proc.pid

    @property
    def is_running(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    @property
    def elapsed(self) -> float:
        import time
        if self._start_time == 0:
            return 0.0
        return time.time() - self._start_time

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the process to finish. Returns exit code."""
        if self._proc is None:
            return -1
        try:
            self._proc.wait(timeout=timeout)
            return self._proc.returncode
        except subprocess.TimeoutExpired:
            return -1

    def terminate_graceful(self, grace_seconds: float = 10.0) -> int:
        """Send SIGTERM, wait grace period, then SIGKILL if needed."""
        if self._proc is None or self._proc.poll() is not None:
            return self._proc.returncode if self._proc else -1

        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

        try:
            self._proc.wait(timeout=grace_seconds)
            return self._proc.returncode
        except subprocess.TimeoutExpired:
            pass

        # Force kill
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

        self._proc.wait()
        return self._proc.returncode

    def kill(self) -> int:
        """Send SIGKILL immediately."""
        if self._proc is None or self._proc.poll() is not None:
            return self._proc.returncode if self._proc else -1

        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

        self._proc.wait()
        return self._proc.returncode
