# AI生成
"""Remote-worktree transport: each task gets an independent repo copy on a remote host.

Mirrors PowerShell Invoke-RemoteWorktreeWorker + Export-WorkerBundle +
Initialize-RemoteWorkspace + Import-WorkerBundle.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..codearts import (
    get_mode_flag,
    new_worker_run_arguments,
    build_worker_core_prompt,
    REQUIRED_MODEL,
)
from ..git_ops import (
    quote_posix,
    remote_worker_guardrail_prefix,
    export_worker_bundle,
    import_worker_bundle,
    resolve_baseline,
    is_git_repo,
    sha256_file,
)
from ..config import assert_safe_id
from .base import TransportBase, TransportResult


class RemoteWorktreeTransport(TransportBase):
    """Export baseline bundle, init remote workspace, run worker, import results."""

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

        host_name = getattr(project, "ssh_host", None)
        if not host_name:
            raise ValueError("remote-worktree project missing sshHost")
        remote_workspace_root = getattr(project, "remote_workspace_root", None)
        if not remote_workspace_root:
            raise ValueError("remote-worktree project missing remoteWorkspaceRoot")

        project_root = project.project_root
        if not is_git_repo(project_root):
            raise ValueError(f"Not a git repo: {project_root}")

        # Resolve baseline
        baseline_sha = resolve_baseline(project_root, baseline)

        # Resolve remote CLI
        remote_cli = "codearts"
        if worker and getattr(worker, "cli_path", None):
            remote_cli = worker.cli_path
        elif getattr(project, "remote_cli_path", None):
            remote_cli = project.remote_cli_path
        if remote_cli != "codearts" and not remote_cli.startswith("/"):
            raise ValueError(f"remoteCliPath must be absolute or codearts: {remote_cli}")

        # Get instructions
        instructions = self._get_instructions(task_dir)
        worker_contract = task_dir.parent.parent / "protocol" / "WORKER.md"
        meta_path = task_dir / "META.json"

        # Export bundle
        export_result = export_worker_bundle(project_root, baseline_sha, task_id)

        # Initialize remote workspace
        init_result = self._initialize_remote_workspace(
            host_name, remote_workspace_root, task_id,
            export_result, baseline_sha,
            str(worker_contract), str(meta_path), instructions,
            remote_cli,
        )

        # Build prompt
        prompt = build_worker_core_prompt(
            worker_contract=init_result["remote_worker_contract"],
            meta_path=init_result["remote_meta_path"],
            instructions=init_result["remote_instruction_paths"],
            outbox_path=init_result["remote_outbox"],
            project_path=init_result["remote_repo"],
        )

        # Build remote command
        mode_flag = get_mode_flag(mode)
        args = new_worker_run_arguments(
            prompt=prompt, model=REQUIRED_MODEL, mode_flag=mode_flag,
            task_id=task_id, session_id=session_id,
        )
        remote_run_segment = " ".join(quote_posix(a) for a in args)
        guardrail = remote_worker_guardrail_prefix()
        run_command = (
            f"{guardrail}; cd -- {quote_posix(init_result['remote_repo'])} "
            f"&& {remote_cli} {remote_run_segment}"
        )

        session_mode = "resume" if session_id else "new"
        local_outbox = task_dir / "outbox"
        local_outbox.mkdir(parents=True, exist_ok=True)
        remote_outbox = init_result["remote_outbox"]

        # Run via SSH
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", host_name, run_command],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
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

        # Salvage on failure/timeout
        if result.exit_code != 0 or result.timed_out:
            salvage = self._salvage_remote(
                host_name, init_result["remote_repo"], task_id,
                task_dir / "evidence",
            )
            if salvage:
                result.salvage_path = salvage

        # Import worker bundle on success
        if result.exit_code == 0:
            try:
                import_result = import_worker_bundle(
                    host_name, init_result["remote_repo"],
                    init_result["remote_branch"], project_root,
                    task_id, baseline_sha,
                )
                result.imported_sha = import_result["imported_sha"]
                result.bundle_sha256 = import_result["sha256"]
                result.baseline_sha = baseline_sha
            except Exception as e:
                result.import_error = str(e)

        # Fetch outbox
        self.run_captured(
            ["scp", "-q", "-r", f"{host_name}:{remote_outbox}/.", str(local_outbox)],
            timeout=120,
        )

        self._write_logs(task_dir, task_id, attempt, result)
        return result

    def _initialize_remote_workspace(
        self,
        host_name: str,
        remote_workspace_root: str,
        task_id: str,
        export_result: dict,
        baseline_sha: str,
        worker_contract_path: str,
        meta_path: str,
        instruction_paths: list[str],
        remote_cli: str = "codearts",
    ) -> dict:
        """Initialize remote workspace: create dirs, copy files, fetch bundle."""
        assert_safe_id(task_id, "TaskId")

        remote_root = remote_workspace_root.rstrip("/")
        remote_task_dir = f"{remote_root}/{task_id}"
        remote_repo = f"{remote_task_dir}/repo"
        remote_protocol = f"{remote_task_dir}/protocol"
        remote_inbox = f"{remote_task_dir}/inbox"
        remote_outbox = f"{remote_task_dir}/outbox"
        remote_bundle = f"{remote_task_dir}/export.bundle"
        remote_branch = f"task/{task_id}"

        # Init remote dirs and git repo
        init_cmd = (
            f"umask 077 && test ! -e {quote_posix(remote_task_dir)} "
            f"&& mkdir -p {quote_posix(remote_repo)} {quote_posix(remote_protocol)} "
            f"{quote_posix(remote_inbox)} {quote_posix(remote_outbox)} "
            f"&& git init -q {quote_posix(remote_repo)} "
            f"&& git -C {quote_posix(remote_repo)} config user.name Bridge "
            f"&& git -C {quote_posix(remote_repo)} config user.email bridge@local"
        )
        ec, out, err = self.run_captured(
            ["ssh", "-o", "BatchMode=yes", host_name, init_cmd], timeout=60
        )
        if ec != 0:
            raise ValueError(f"Remote workspace init failed: {err}")

        # Remap allowedPaths in META.json
        meta_for_remote = meta_path
        try:
            meta_obj = json.loads(Path(meta_path).read_text(encoding="utf-8"))
            if "allowedPaths" in meta_obj:
                meta_obj["allowedPaths"] = [remote_repo]
                remapped = Path(tempfile.gettempdir()) / "META-remapped.json"
                remapped.write_text(json.dumps(meta_obj), encoding="utf-8")
                meta_for_remote = str(remapped)
        except (json.JSONDecodeError, OSError):
            pass

        # Copy files to remote
        transfers = [
            (export_result["bundle_file"], remote_bundle, "bundle"),
            (worker_contract_path, f"{remote_protocol}/WORKER.md", "worker-contract"),
            (meta_for_remote, f"{remote_task_dir}/META.json", "task-meta"),
        ]
        remote_instruction_paths = []
        for instr in instruction_paths:
            remote_instr = f"{remote_inbox}/{Path(instr).name}"
            transfers.append((instr, remote_instr, Path(instr).name))
            remote_instruction_paths.append(remote_instr)

        for local_path, remote_path, label in transfers:
            ec, out, err = self.run_captured(
                ["scp", "-q", local_path, f"{host_name}:{remote_path}"], timeout=60
            )
            if ec != 0:
                raise ValueError(f"Remote copy failed for {label}: {err}")

        # Fetch bundle on remote
        fetch_cmd = (
            f"git -C {quote_posix(remote_repo)} fetch -q {quote_posix(remote_bundle)} "
            f"{baseline_sha}:refs/heads/{remote_branch} "
            f"&& git -C {quote_posix(remote_repo)} checkout -q {remote_branch}"
        )
        ec, out, err = self.run_captured(
            ["ssh", "-o", "BatchMode=yes", host_name, fetch_cmd], timeout=60
        )
        if ec != 0:
            raise ValueError(f"Remote bundle fetch failed: {err}")

        return {
            "remote_repo": remote_repo,
            "remote_branch": remote_branch,
            "remote_task_dir": remote_task_dir,
            "remote_outbox": remote_outbox,
            "remote_meta_path": f"{remote_task_dir}/META.json",
            "remote_worker_contract": f"{remote_protocol}/WORKER.md",
            "remote_instruction_paths": remote_instruction_paths,
        }

    def _salvage_remote(
        self,
        host_name: str,
        remote_repo: str,
        task_id: str,
        local_evidence_dir: Path,
    ) -> str | None:
        """Salvage uncommitted changes from remote repo on failure."""
        assert_safe_id(task_id, "TaskId")
        local_evidence_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        remote_diff = f"/tmp/salvage-{task_id}-{stamp}.diff"
        remote_status = f"/tmp/salvage-{task_id}-{stamp}.status"
        remote_tar = f"/tmp/salvage-{task_id}-{stamp}.tar.gz"

        cmd = (
            f"git -C {quote_posix(remote_repo)} diff HEAD > {quote_posix(remote_diff)} 2>/dev/null; "
            f"git -C {quote_posix(remote_repo)} status --short > {quote_posix(remote_status)} 2>/dev/null; "
            f"tar -czf {quote_posix(remote_tar)} -C /tmp "
            f"{Path(remote_diff).name} {Path(remote_status).name} 2>/dev/null; "
            f"echo $?"
        )
        self.run_captured(["ssh", "-o", "BatchMode=yes", host_name, cmd], timeout=30)

        local_tar = local_evidence_dir / f"salvage-{task_id}-{stamp}.tar.gz"
        ec, _, _ = self.run_captured(
            ["scp", "-o", "BatchMode=yes", "-q", f"{host_name}:{remote_tar}", str(local_tar)],
            timeout=30,
        )
        if local_tar.is_file():
            try:
                subprocess.run(
                    ["tar", "-xzf", str(local_tar), "-C", str(local_evidence_dir)],
                    capture_output=True, timeout=10,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
            return str(local_tar)
        return None

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