# AI生成
"""Remote git worktree workspace manager.

Exports a git bundle locally, transfers it to a remote host via SSH,
creates a remote workspace with the bundle fetched, and provides
cleanup/salvage operations. This extracts workspace management
from the old transport/remote_worktree.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..git_ops import (
    quote_posix, remote_worker_guardrail_prefix,
    export_worker_bundle, resolve_baseline, is_git_repo, sha256_file,
)
from ..config import assert_safe_id
from .base import WorkspaceManager, WorkspaceResult


class RemoteWorktreeWorkspace(WorkspaceManager):
    """Manage remote worktree workspaces via SSH."""

    @property
    def workspace_type(self) -> str:
        return "remote-worktree"

    def prepare(
        self,
        project: Any,
        task_id: str,
        task_dir: Path,
        baseline: str | None = None,
    ) -> WorkspaceResult:
        assert_safe_id(task_id, "TaskId")

        host_name = getattr(project, "ssh_host", None)
        if not host_name:
            raise ValueError("remote-worktree project missing sshHost")
        remote_workspace_root = getattr(project, "remote_workspace_root", None)
        if not remote_workspace_root:
            raise ValueError("remote-worktree project missing remoteWorkspaceRoot")

        project_root = project.project_root
        if not is_git_repo(project_root):
            raise ValueError(f"Not a git repo: {project_root}")

        baseline_sha = resolve_baseline(project_root, baseline)
        branch = f"task/{task_id}"

        # Export bundle
        export_result = export_worker_bundle(project_root, baseline_sha, task_id)

        # Set up remote dirs
        remote_root = remote_workspace_root.rstrip("/")
        remote_task_dir = f"{remote_root}/{task_id}"
        remote_repo = f"{remote_task_dir}/repo"
        remote_protocol = f"{remote_task_dir}/protocol"
        remote_inbox = f"{remote_task_dir}/inbox"
        remote_outbox = f"{remote_task_dir}/outbox"
        remote_bundle = f"{remote_task_dir}/export.bundle"

        # Init remote dirs and git repo
        init_cmd = (
            f"umask 077 && test ! -e {quote_posix(remote_task_dir)} "
            f"&& mkdir -p {quote_posix(remote_repo)} {quote_posix(remote_protocol)} "
            f"{quote_posix(remote_inbox)} {quote_posix(remote_outbox)} "
            f"&& git init -q {quote_posix(remote_repo)} "
            f"&& git -C {quote_posix(remote_repo)} config user.name Bridge "
            f"&& git -C {quote_posix(remote_repo)} config user.email bridge@local"
        )
        ec, _, err = self._ssh(host_name, init_cmd, timeout=60)
        if ec != 0:
            raise ValueError(f"Remote workspace init failed: {err}")

        # Transfer bundle
        ec, _, err = self._scp(
            export_result["bundle_file"], f"{host_name}:{remote_bundle}", timeout=60
        )
        if ec != 0:
            raise ValueError(f"Bundle transfer failed: {err}")

        # Fetch bundle on remote
        fetch_cmd = (
            f"git -C {quote_posix(remote_repo)} fetch -q {quote_posix(remote_bundle)} "
            f"{baseline_sha}:refs/heads/{branch} "
            f"&& git -C {quote_posix(remote_repo)} checkout -q {branch}"
        )
        ec, _, err = self._ssh(host_name, fetch_cmd, timeout=60)
        if ec != 0:
            raise ValueError(f"Remote bundle fetch failed: {err}")

        # Transfer protocol and task files
        worker_contract = task_dir.parent.parent / "protocol" / "WORKER.md"
        meta_path = task_dir / "META.json"

        # Remap allowedPaths in META.json
        meta_for_remote = str(meta_path)
        try:
            meta_obj = json.loads(Path(meta_path).read_text(encoding="utf-8"))
            if "allowedPaths" in meta_obj:
                meta_obj["allowedPaths"] = [remote_repo]
                remapped = Path(tempfile.gettempdir()) / "META-remapped.json"
                remapped.write_text(json.dumps(meta_obj), encoding="utf-8")
                meta_for_remote = str(remapped)
        except (json.JSONDecodeError, OSError):
            pass

        transfers = [
            (str(worker_contract), f"{remote_protocol}/WORKER.md"),
            (meta_for_remote, f"{remote_task_dir}/META.json"),
        ]
        # Transfer instruction files
        inbox = task_dir / "inbox"
        instruction_files = sorted(inbox.glob("*.md"))
        remote_instruction_paths = []
        for instr in instruction_files:
            remote_instr = f"{remote_inbox}/{instr.name}"
            transfers.append((str(instr), remote_instr))
            remote_instruction_paths.append(remote_instr)

        for local_path, remote_path in transfers:
            ec, _, err = self._scp(local_path, f"{host_name}:{remote_path}", timeout=60)
            if ec != 0:
                raise ValueError(f"Remote copy failed for {local_path}: {err}")

        return WorkspaceResult(
            workspace_path=remote_repo,
            branch=branch,
            baseline_sha=baseline_sha,
            is_remote=True,
            remote_host=host_name,
            repo_path=remote_repo,
            outbox_path=remote_outbox,
            inbox_path=remote_inbox,
            meta_path=f"{remote_task_dir}/META.json",
            contract_path=f"{remote_protocol}/WORKER.md",
            instruction_paths=remote_instruction_paths,
            extra={
                "transport": "ssh",
                "remote_task_dir": remote_task_dir,
                "remote_bundle": remote_bundle,
                "bundle_file": export_result["bundle_file"],
            },
        )

    def cleanup(
        self,
        task_id: str,
        workspace_result: WorkspaceResult,
    ) -> None:
        if not workspace_result.is_remote:
            return
        host = workspace_result.remote_host
        remote_task_dir = workspace_result.extra.get("remote_task_dir", "")
        if not host or not remote_task_dir:
            return
        self._ssh(host, f"rm -rf {quote_posix(remote_task_dir)}", timeout=30)

    def salvage(
        self,
        task_id: str,
        workspace_result: WorkspaceResult,
        evidence_dir: Path,
    ) -> str | None:
        if not workspace_result.is_remote:
            return None
        assert_safe_id(task_id, "TaskId")

        host = workspace_result.remote_host
        remote_repo = workspace_result.repo_path
        evidence_dir.mkdir(parents=True, exist_ok=True)
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
        self._ssh(host, cmd, timeout=30)

        local_tar = evidence_dir / f"salvage-{task_id}-{stamp}.tar.gz"
        self._scp(f"{host}:{remote_tar}", str(local_tar), timeout=30)
        if local_tar.is_file():
            try:
                subprocess.run(
                    ["tar", "-xzf", str(local_tar), "-C", str(evidence_dir)],
                    capture_output=True, timeout=10,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
            return str(local_tar)
        return None

    @staticmethod
    def _ssh(host: str, command: str, timeout: int = 60) -> tuple[int, str, str]:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", host, command],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr

    @staticmethod
    def _scp(src: str, dst: str, timeout: int = 60) -> tuple[int, str, str]:
        r = subprocess.run(
            ["scp", "-q", "-o", "BatchMode=yes", src, dst],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
