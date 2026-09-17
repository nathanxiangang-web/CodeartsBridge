# AI生成
"""SSH-shell transport: CodeArts CLI runs locally, project is on a remote host.

Mirrors PowerShell Invoke-SshShellWorker.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..codearts import (
    find_codearts_cli,
    get_mode_flag,
    new_worker_run_arguments,
    build_worker_core_prompt,
    get_remote_access_directive,
    REQUIRED_MODEL,
)
from .base import TransportBase, TransportResult


class SshShellTransport(TransportBase):
    """Run local CodeArts CLI but operate on a remote project via SSH."""

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
        task_dir = Path(task_dir)

        cli = find_codearts_cli()
        if not cli or not Path(cli).is_file():
            raise ValueError("codearts CLI not found. Run the official installer first, then rerun doctor.")

        host_name = getattr(project, "ssh_host", None)
        if not host_name:
            raise ValueError("ssh-shell project missing sshHost")

        remote_project_path = project.project_root
        instructions = self._get_instructions(task_dir)
        worker_contract = task_dir.parent.parent / "protocol" / "WORKER.md"
        meta_path = task_dir / "META.json"
        outbox_path = task_dir / "outbox"

        remote_directive = get_remote_access_directive(host_name, remote_project_path)
        prompt = build_worker_core_prompt(
            worker_contract=str(worker_contract),
            meta_path=str(meta_path),
            instructions=instructions,
            outbox_path=str(outbox_path),
            project_path=remote_project_path,
            remote_directive=remote_directive,
        )

        mode_flag = get_mode_flag(mode)
        args = new_worker_run_arguments(
            prompt=prompt, model=REQUIRED_MODEL, mode_flag=mode_flag,
            task_id=task_id, session_id=session_id,
        )

        bridge_root = task_dir.parent.parent
        session_mode = "resume" if session_id else "new"

        try:
            r = subprocess.run(
                [cli] + args,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=str(bridge_root),
            )
            result = TransportResult(
                exit_code=r.returncode,
                stdout=r.stdout,
                stderr=r.stderr,
                session_mode=session_mode,
            )
        except subprocess.TimeoutExpired as e:
            result = TransportResult(
                exit_code=-1,
                stdout=e.stdout or "",
                stderr=e.stderr or "",
                timed_out=True,
                session_mode=session_mode,
            )

        self._write_logs(task_dir, task_id, attempt, result)
        return result

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