# AI生成
"""Git operations: bundle export/import, worktree, baseline resolution.

Mirrors PowerShell Export-WorkerBundle, Import-WorkerBundle, Get-BaselineSha,
Test-GitRepo, Capture-WorkerCommit, New-TaskWorktree.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .config import assert_safe_id

_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SAFE_POSIX_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")


def run_git(args: list[str], cwd: str | Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def is_git_repo(path: str | Path) -> bool:
    r = run_git(["rev-parse", "--is-inside-work-tree"], cwd=path, timeout=10)
    return r.returncode == 0 and r.stdout.strip() == "true"


def git_has_commit(path: str | Path) -> bool:
    r = run_git(["rev-parse", "HEAD"], cwd=path, timeout=10)
    return r.returncode == 0


def git_is_dirty(path: str | Path) -> bool:
    r = run_git(["status", "--porcelain"], cwd=path, timeout=10)
    return r.returncode == 0 and bool(r.stdout.strip())


def resolve_baseline(project_root: str | Path, baseline: str | None = None) -> str:
    """Resolve a baseline ref to a canonical commit SHA."""
    ref = baseline if baseline else "HEAD"
    r = run_git(["rev-parse", "-q", "--verify", f"{ref}^{{commit}}"], cwd=project_root, timeout=10)
    if r.returncode != 0 or not r.stdout.strip():
        raise ValueError(f"Cannot resolve baseline {ref} in {project_root}")
    return r.stdout.strip()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def export_worker_bundle(project_root: str | Path, baseline_sha: str, task_id: str) -> dict:
    """Export a git bundle for the baseline commit.

    Returns: {bundle_file, sha256, baseline_sha}
    """
    assert_safe_id(task_id, "TaskId")
    bundle_dir = Path(tempfile.gettempdir()) / "bridge-bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_file = bundle_dir / f"export-{task_id}.bundle"
    if bundle_file.exists():
        bundle_file.unlink()

    tmp_ref = f"refs/tmp/export-{task_id}"
    run_git(["update-ref", tmp_ref, baseline_sha], cwd=project_root)
    r = run_git(["bundle", "create", str(bundle_file), tmp_ref], cwd=project_root)
    run_git(["update-ref", "-d", tmp_ref], cwd=project_root)

    if r.returncode != 0 or not bundle_file.is_file():
        raise ValueError(f"git bundle create failed for {task_id}")
    return {
        "bundle_file": str(bundle_file),
        "sha256": sha256_file(bundle_file),
        "baseline_sha": baseline_sha,
    }


def import_worker_bundle(
    host_name: str,
    remote_repo: str,
    remote_branch: str,
    project_root: str | Path,
    task_id: str,
    baseline_sha: str,
) -> dict:
    """Import worker result from remote as a namespaced ref.

    Returns: {imported_sha, bundle_file, sha256, namespaced_ref, ancestry_valid}
    """
    assert_safe_id(task_id, "TaskId")
    bundle_dir = Path(tempfile.gettempdir()) / "bridge-bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    local_bundle = bundle_dir / f"import-{task_id}.bundle"
    if local_bundle.exists():
        local_bundle.unlink()

    remote_bundle = f"/tmp/result-{task_id}.bundle"
    create_cmd = f"git -C {quote_posix(remote_repo)} bundle create {quote_posix(remote_bundle)} {remote_branch}"
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host_name, create_cmd],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise ValueError(f"Remote bundle create failed: {r.stderr}")

    r = subprocess.run(
        ["scp", "-q", f"{host_name}:{remote_bundle}", str(local_bundle)],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise ValueError(f"Result bundle SCP failed: {r.stderr}")

    namespaced_ref = f"refs/worker/{task_id}/result"
    refspec = f"{remote_branch}:{namespaced_ref}"
    run_git(["fetch", "-q", str(local_bundle), refspec], cwd=project_root)

    r = run_git(["rev-parse", namespaced_ref], cwd=project_root, timeout=10)
    imported_sha = r.stdout.strip()
    if not imported_sha:
        raise ValueError(f"Cannot resolve imported ref for {task_id}")

    r = run_git(["merge-base", "--is-ancestor", baseline_sha, imported_sha], cwd=project_root, timeout=10)
    if r.returncode != 0:
        raise ValueError(f"Imported commit is not a descendant of baseline for {task_id}")

    return {
        "imported_sha": imported_sha,
        "bundle_file": str(local_bundle),
        "sha256": sha256_file(local_bundle),
        "namespaced_ref": namespaced_ref,
        "ancestry_valid": True,
    }


def quote_posix(value: str) -> str:
    """POSIX shell single-quote escaping. Matches PowerShell Quote-Posix."""
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError("SSH args contain disallowed control characters")
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_worker_guardrail_prefix() -> str:
    """Git guardrail exports to prevent credential leaks on remote workers."""
    exports = [
        "export GIT_TERMINAL_PROMPT=0",
        "export GIT_ASKPASS=",
        "export GIT_CONFIG_NOSYSTEM=1",
        "export GIT_CONFIG_SYSTEM=/dev/null",
        "export GIT_CONFIG_GLOBAL=/dev/null",
        "export GIT_CONFIG_COUNT=7",
        "export GIT_CONFIG_KEY_0=credential.helper",
        "export GIT_CONFIG_VALUE_0=",
        "export GIT_CONFIG_KEY_1=remote.origin.pushurl",
        "export GIT_CONFIG_VALUE_1=invalid://bridge-blocked-push",
        "export GIT_CONFIG_KEY_2=protocol.file.allow",
        "export GIT_CONFIG_VALUE_2=never",
        "export GIT_CONFIG_KEY_3=protocol.git.allow",
        "export GIT_CONFIG_VALUE_3=never",
        "export GIT_CONFIG_KEY_4=protocol.http.allow",
        "export GIT_CONFIG_VALUE_4=never",
        "export GIT_CONFIG_KEY_5=protocol.https.allow",
        "export GIT_CONFIG_VALUE_5=never",
        "export GIT_CONFIG_KEY_6=protocol.ssh.allow",
        "export GIT_CONFIG_VALUE_6=never",
    ]
    unsets = [
        "GIT_USERNAME", "GIT_PASSWORD", "GIT_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN",
        "SSH_AUTH_SOCK", "SSH_AGENT_PID", "SSH_KEY_PATH", "GIT_SSH_KEYPATH", "GIT_SSH_KEY",
        "GIT_SSH_COMMAND", "GIT_SSH_VARIANT",
        "GIT_CREDENTIAL_HELPER", "GIT_CREDENTIAL_MANAGER", "GIT_CREDENTIAL_MANAGER_HELPER",
        "GIT_CREDENTIAL_STORE", "GCM_INTERACTIVE", "GCM_PROVIDER", "GCM_PLUGINS",
    ]
    return "; ".join(exports) + "; unset " + " ".join(unsets) + " 2>/dev/null || true"