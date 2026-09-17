# AI生成
"""Transport base class and shared result type."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..codearts import sensitive_mask


@dataclass
class TransportResult:
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False
    session_id: str | None = None
    session_mode: str | None = None
    imported_sha: str | None = None
    bundle_sha256: str | None = None
    baseline_sha: str | None = None
    salvage_path: str | None = None
    import_error: str | None = None
    assistance_requested: bool = False


class TransportBase:
    """Base class for all transport implementations."""

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
    ) -> TransportResult:
        raise NotImplementedError

    @staticmethod
    def run_captured(
        args: list[str],
        timeout: int = 60,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Run a command with captured output and timeout. Returns (exit_code, stdout, stderr)."""
        merged_env = None
        if env:
            merged_env = os.environ.copy()
            merged_env.update(env)
        try:
            r = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=merged_env,
            )
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired as e:
            return -1, e.stdout or "", e.stderr or ""

    @staticmethod
    def run_captured_with_logs(
        args: list[str],
        task_dir: str | Path,
        log_prefix: str,
        timeout: int = 60,
        cwd: str | None = None,
    ) -> TransportResult:
        """Run a command, write stdout/stderr to log files, return TransportResult."""
        task_dir = Path(task_dir)
        logs_dir = task_dir / "runtime" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        try:
            r = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            exit_code = r.returncode
            stdout = r.stdout
            stderr = r.stderr
        except subprocess.TimeoutExpired as e:
            exit_code = -1
            stdout = e.stdout or ""
            stderr = e.stderr or ""

        # Write logs
        stdout_log = logs_dir / f"{log_prefix}.stdout.log"
        stderr_log = logs_dir / f"{log_prefix}.stderr.log"
        stdout_log.write_text(stdout, encoding="utf-8")
        stderr_log.write_text(stderr, encoding="utf-8")

        return TransportResult(exit_code=exit_code, stdout=stdout, stderr=stderr)