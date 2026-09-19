# AI生成
"""SSH transport: CodeArts CLI runs on a remote host with its own account.

Mirrors PowerShell Invoke-SshWorker.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..codearts import (
    get_mode_flag,
    new_worker_run_arguments,
    build_worker_core_prompt,
    get_worker_local_access_directive,
    REQUIRED_MODEL,
    THINK_LANGUAGE_DIRECTIVE,
)
from ..git_ops import quote_posix
from .base import TransportBase, TransportResult


class SshTransport(TransportBase):
    """Run CodeArts CLI on a remote host via SSH."""

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

        host_name = getattr(project, "ssh_host", None)
        if not host_name:
            raise ValueError("SSH project missing sshHost")
        remote_bridge_root = getattr(project, "remote_bridge_root", None)
        if not remote_bridge_root:
            raise ValueError("SSH project missing remoteBridgeRoot")

        # Resolve remote CLI path
        remote_cli = "codearts"
        if worker and getattr(worker, "cli_path", None):
            remote_cli = worker.cli_path
        elif getattr(project, "remote_cli_path", None):
            remote_cli = project.remote_cli_path
        if remote_cli != "codearts" and not remote_cli.startswith("/"):
            raise ValueError(f"remoteCliPath must be absolute or codearts: {remote_cli}")

        remote_root = remote_bridge_root.rstrip("/")
        remote_task = f"{remote_root}/tasks/{task_dir.name}"
        remote_protocol = f"{remote_root}/protocol"
        remote_outbox = f"{remote_task}/outbox"

        # Get instructions
        instructions = self._get_instructions(task_dir)
        worker_contract = task_dir.parent.parent / "protocol" / "WORKER.md"
        meta_path = task_dir / "META.json"

        # Prepare remote directories
        prepare_cmd = f"mkdir -p {quote_posix(remote_protocol)} {quote_posix(remote_task + '/inbox')} {quote_posix(remote_outbox)}"
        ec, out, err = self.run_captured(
            ["ssh", "-o", "BatchMode=yes", host_name, prepare_cmd], timeout=60
        )
        if ec != 0:
            return TransportResult(exit_code=ec, stdout=out, stderr=err)

        # Copy files to remote
        copies = [
            (str(worker_contract), f"{remote_protocol}/WORKER.md"),
            (str(meta_path), f"{remote_task}/META.json"),
        ]
        for instr in instructions:
            copies.append((instr, f"{remote_task}/inbox/{Path(instr).name}"))

        for local_path, remote_path in copies:
            ec, out, err = self.run_captured(
                ["scp", "-q", local_path, f"{host_name}:{remote_path}"], timeout=60
            )
            if ec != 0:
                return TransportResult(exit_code=ec, stdout=out, stderr=err)

        # Build remote prompt
        remote_instruction_paths = [f"{remote_task}/inbox/{Path(instr).name}" for instr in instructions]
        remote_project_path = project.project_root
        remote_directive = get_worker_local_access_directive(remote_project_path)
        prompt = build_worker_core_prompt(
            worker_contract=f"{remote_protocol}/WORKER.md",
            meta_path=f"{remote_task}/META.json",
            instructions=remote_instruction_paths,
            outbox_path=remote_outbox,
            project_path=remote_project_path,
            remote_directive=remote_directive,
        )

        # Build remote command
        mode_flag = get_mode_flag(mode)
        args = new_worker_run_arguments(
            prompt=prompt, model=model or REQUIRED_MODEL, mode_flag=mode_flag,
            task_id=task_id, session_id=session_id,
        )
        remote_run_segment = " ".join(quote_posix(a) for a in args)
        inner_cmd = f"{remote_cli} {remote_run_segment}"
        run_command = f"script -qfc {quote_posix(inner_cmd)} {quote_posix(remote_task + '/session.log')}"
        cd_part = f"cd -- {quote_posix(remote_project_path)}"
        full_cmd = f"{cd_part} && {run_command}"

        session_mode = "resume" if session_id else "new"

        # Run via SSH with two-phase timeout (soft checkpoint + hard kill)
        soft_checkpointed = False
        try:
            proc = subprocess.Popen(
                ["ssh", "-o", "BatchMode=yes", host_name, full_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            elapsed = 0
            poll_interval = 5  # seconds
            while True:
                try:
                    stdout, stderr = proc.communicate(timeout=poll_interval)
                    result = TransportResult(
                        exit_code=proc.returncode,
                        stdout=stdout,
                        stderr=stderr,
                        soft_checkpointed=soft_checkpointed,
                        session_mode=session_mode,
                    )
                    break
                except subprocess.TimeoutExpired:
                    elapsed += poll_interval
                    # Soft timeout: checkpoint (fetch outbox) but let worker continue
                    if (
                        not soft_checkpointed
                        and soft_timeout_seconds > 0
                        and elapsed >= soft_timeout_seconds
                    ):
                        soft_checkpointed = True
                        self._fetch_outbox(host_name, remote_outbox, task_dir)
                    # Hard timeout: kill and trigger assistance
                    if timeout_seconds > 0 and elapsed >= timeout_seconds:
                        proc.kill()
                        stdout, stderr = proc.communicate(timeout=10)
                        result = TransportResult(
                            exit_code=-1,
                            stdout=stdout or "",
                            stderr=stderr or "",
                            timed_out=True,
                            assistance_requested=True,
                            soft_checkpointed=soft_checkpointed,
                            session_mode=session_mode,
                        )
                        break
        except Exception as e:
            result = TransportResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                session_mode=session_mode,
            )

        # Fetch outbox (final fetch after process completes)
        local_outbox = task_dir / "outbox"
        local_outbox.mkdir(parents=True, exist_ok=True)
        self.run_captured(
            ["scp", "-q", "-r", f"{host_name}:{remote_outbox}/.", str(local_outbox)],
            timeout=120,
        )

        self._write_logs(task_dir, task_id, attempt, result)
        return result

    @staticmethod
    def _fetch_outbox(host_name: str, remote_outbox: str, task_dir: Path) -> None:
        """Fetch outbox from remote (soft checkpoint)."""
        local_outbox = task_dir / "outbox"
        local_outbox.mkdir(parents=True, exist_ok=True)
        SshTransport.run_captured(
            ["scp", "-q", "-r", f"{host_name}:{remote_outbox}/.", str(local_outbox)],
            timeout=60,
        )

    @staticmethod
    def _get_instructions(task_dir: Path) -> list[str]:
        inbox = task_dir / "inbox"
        files = sorted(inbox.glob("*.md"))
        if not files:
            raise ValueError("No instruction files in task inbox")
        return [str(f) for f in files]

    @staticmethod
    def _write_logs(task_dir: Path, task_id: str, attempt: int, result: TransportResult) -> None:
        logs_dir = task_dir / "runtime" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{task_id}.attempt-{attempt:03d}"
        (logs_dir / f"{prefix}.stdout.log").write_text(result.stdout, encoding="utf-8")
        (logs_dir / f"{prefix}.stderr.log").write_text(result.stderr, encoding="utf-8")