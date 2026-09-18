# AI生成
"""Production-grade doctor and worker readiness probes.

P1-01: Comprehensive health checks for bridge doctor command.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


READY = "READY"
DEGRADED = "DEGRADED"
AUTH_REQUIRED = "AUTH_REQUIRED"
QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
OFFLINE = "OFFLINE"


@dataclass
class CheckResult:
    name: str
    passed: bool
    status: str
    detail: str = ""


@dataclass
class WorkerReadiness:
    worker_id: str
    state: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.state == READY


def check_ssh_connectivity(host: str | None) -> CheckResult:
    if not host:
        return CheckResult("ssh_connectivity", False, OFFLINE, "no host configured")
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        return CheckResult("ssh_connectivity", False, OFFLINE, "ssh binary not found")
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", host, "echo", "ok"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "ok" in result.stdout:
            return CheckResult("ssh_connectivity", True, READY, f"connected to {host}")
        return CheckResult("ssh_connectivity", False, OFFLINE, f"ssh failed: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        return CheckResult("ssh_connectivity", False, OFFLINE, f"timeout connecting to {host}")
    except Exception as e:
        return CheckResult("ssh_connectivity", False, OFFLINE, f"error: {e}")


def check_cli_version(cli_path: str | None) -> CheckResult:
    if not cli_path or not Path(cli_path).is_file():
        return CheckResult("cli_version", False, DEGRADED, "CLI not found")
    try:
        result = subprocess.run(
            [cli_path, "--version"], capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return CheckResult("cli_version", True, READY, f"version: {version}")
        return CheckResult("cli_version", False, DEGRADED, f"exit code {result.returncode}")
    except Exception as e:
        return CheckResult("cli_version", False, DEGRADED, f"error: {e}")


def check_repo_existence(repo_path: str | None) -> CheckResult:
    if not repo_path:
        return CheckResult("repo_existence", False, DEGRADED, "no repo path configured")
    p = Path(repo_path)
    if not p.is_dir():
        return CheckResult("repo_existence", False, OFFLINE, f"repo not found: {repo_path}")
    if not (p / ".git").is_dir():
        return CheckResult("repo_existence", False, DEGRADED, f"not a git repo: {repo_path}")
    return CheckResult("repo_existence", True, READY, f"repo exists: {repo_path}")


def check_repo_clean_state(repo_path: str | None) -> CheckResult:
    if not repo_path or not Path(repo_path).is_dir():
        return CheckResult("repo_clean_state", False, DEGRADED, "repo not accessible")
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo_path,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            if not result.stdout.strip():
                return CheckResult("repo_clean_state", True, READY, "working tree clean")
            lines = result.stdout.strip().split("\n")
            return CheckResult("repo_clean_state", False, DEGRADED, f"{len(lines)} uncommitted changes")
        return CheckResult("repo_clean_state", False, DEGRADED, "git status failed")
    except Exception as e:
        return CheckResult("repo_clean_state", False, DEGRADED, f"error: {e}")


def check_workspace_writable(ws_path: str | None) -> CheckResult:
    if not ws_path:
        return CheckResult("workspace_writable", False, DEGRADED, "no workspace path")
    p = Path(ws_path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        test_file = p / ".bridge_health_check"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return CheckResult("workspace_writable", True, READY, f"writable: {ws_path}")
    except Exception as e:
        return CheckResult("workspace_writable", False, OFFLINE, f"not writable: {e}")


def check_git_available() -> CheckResult:
    git_bin = shutil.which("git")
    if git_bin:
        return CheckResult("git_available", True, READY, f"git: {git_bin}")
    return CheckResult("git_available", False, OFFLINE, "git not found")


def check_worker_host_consistency(worker_host: str | None, project_host: str | None) -> CheckResult:
    if not worker_host:
        return CheckResult("host_consistency", True, READY, "local worker, no host check needed")
    if not project_host:
        return CheckResult("host_consistency", False, DEGRADED, "worker has host but project has none")
    if worker_host == project_host:
        return CheckResult("host_consistency", True, READY, f"hosts match: {worker_host}")
    return CheckResult("host_consistency", False, DEGRADED, f"mismatch: worker={worker_host} project={project_host}")


def check_quota_state(quota_file: str | None = None) -> CheckResult:
    if quota_file and Path(quota_file).is_file():
        try:
            data = json.loads(Path(quota_file).read_text(encoding="utf-8"))
            remaining = data.get("remaining", 0)
            if remaining <= 0:
                return CheckResult("quota_state", False, QUOTA_EXHAUSTED, "quota exhausted")
            return CheckResult("quota_state", True, READY, f"remaining: {remaining}")
        except Exception:
            pass
    return CheckResult("quota_state", True, READY, "no quota limit configured")


def check_model_availability(model: str | None) -> CheckResult:
    if not model:
        return CheckResult("model_availability", False, DEGRADED, "no model configured")
    return CheckResult("model_availability", True, READY, f"model: {model}")


def check_codearts_auth(cli_path: str | None) -> CheckResult:
    if not cli_path or not Path(cli_path).is_file():
        return CheckResult("codearts_auth", False, AUTH_REQUIRED, "CLI not found")
    auth_file = Path.home() / ".codearts" / "auth.json"
    if auth_file.is_file():
        try:
            data = json.loads(auth_file.read_text(encoding="utf-8"))
            if data.get("token") or data.get("authenticated"):
                return CheckResult("codearts_auth", True, READY, "authenticated")
        except Exception:
            pass
    return CheckResult("codearts_auth", False, AUTH_REQUIRED, "not authenticated")


def check_stale_tasks(bridge_root: Path) -> CheckResult:
    """Detect tasks in RUNNING state with no live worker process."""
    from .state import get_state
    tasks_root = Path(bridge_root) / "tasks"
    if not tasks_root.exists():
        return CheckResult("stale_tasks", True, READY, "no tasks directory")

    stale = []
    for task_dir in tasks_root.iterdir():
        if not task_dir.is_dir():
            continue
        state = get_state(task_dir)
        status = state.get("status") or state.get("state", "")
        if status != "RUNNING":
            continue
        pid = state.get("processId")
        if pid and _is_process_alive(int(pid)):
            continue
        stale.append(task_dir.name)

    if stale:
        return CheckResult("stale_tasks", False, DEGRADED, f"{len(stale)} stale RUNNING task(s): {', '.join(stale[:5])}")
    return CheckResult("stale_tasks", True, READY, "no stale tasks")


def _is_process_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def run_doctor(
    bridge_root: Path,
    workers: list,
    projects: list,
) -> dict:
    """Run full doctor check and return structured results."""
    results = {
        "bridge_root": str(bridge_root),
        "checks": [],
        "workers": [],
    }

    # Global checks
    results["checks"].append(check_git_available())
    results["checks"].append(check_workspace_writable(str(bridge_root / "workspace")))
    results["checks"].append(check_stale_tasks(bridge_root))

    # Per-worker checks
    for w in workers:
        checks = []
        checks.append(check_ssh_connectivity(getattr(w, "host", None)))
        checks.append(check_cli_version(getattr(w, "cli_path", None)))
        checks.append(check_model_availability(getattr(w, "model", None)))
        checks.append(check_codearts_auth(getattr(w, "cli_path", None)))

        # Determine worker state from checks
        states = [c.status for c in checks]
        if OFFLINE in states:
            state = OFFLINE
        elif AUTH_REQUIRED in states:
            state = AUTH_REQUIRED
        elif QUOTA_EXHAUSTED in states:
            state = QUOTA_EXHAUSTED
        elif DEGRADED in states:
            state = DEGRADED
        else:
            state = READY

        results["workers"].append({
            "worker_id": w.id,
            "state": state,
            "checks": [{"name": c.name, "passed": c.passed, "status": c.status, "detail": c.detail} for c in checks],
        })

    return results


def get_ready_workers(workers: list) -> list:
    """Filter workers that are READY for dispatch."""
    ready = []
    for w in workers:
        if not getattr(w, "enabled", True):
            continue
        checks = []
        host = getattr(w, "host", None)
        if host:
            checks.append(check_ssh_connectivity(host))
        checks.append(check_model_availability(getattr(w, "model", None)))

        states = [c.status for c in checks]
        if OFFLINE not in states and DEGRADED not in states:
            ready.append(w)
    return ready