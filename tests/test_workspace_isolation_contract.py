"""Workspace isolation contract regression tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "bridge@test.local"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Bridge Test"], cwd=path, check=True)
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_workspace_policy_auto_is_transport_aware():
    from bridge.workspace.policy import resolve_workspace_mode

    assert resolve_workspace_mode("auto", "local") == "local-worktree"
    assert resolve_workspace_mode("auto", "ssh") == "existing"
    assert resolve_workspace_mode("auto", "ssh-shell") == "existing"
    assert resolve_workspace_mode("auto", "remote-worktree") == "remote-worktree"
    assert resolve_workspace_mode("existing", "remote-worktree") == "remote-worktree"


def test_workspace_policy_never_silently_downgrades_isolation():
    import pytest
    from bridge.workspace.policy import resolve_workspace_mode

    with pytest.raises(ValueError, match="does not provide an isolated workspace"):
        resolve_workspace_mode("isolated", "ssh")
    with pytest.raises(ValueError, match="not enforceable"):
        resolve_workspace_mode("shared-readonly", "local")


def test_local_auto_runs_transport_inside_task_worktree(tmp_path, monkeypatch):
    import bridge.worker as worker_module
    from bridge.application.task_service import create_task
    from bridge.config import ProjectConfig
    from bridge.transport import TransportResult

    project_root = tmp_path / "project"
    bridge_root = tmp_path / "bridge"
    _init_git_repo(project_root)

    task_id = "local-auto"
    create_task(
        bridge_root=bridge_root,
        project_id="p1",
        worker_id=None,
        role="implement",
        task_id=task_id,
        task_file=None,
    )

    captured = {}

    class FakeLocalTransport:
        def run(self, **kwargs):
            captured.update(kwargs)
            return TransportResult(exit_code=1, stdout="", stderr="")

    monkeypatch.setitem(worker_module.TRANSPORT_MAP, "local", FakeLocalTransport)
    project = ProjectConfig(
        id="p1", transport="local", project_root=str(project_root)
    )

    result = worker_module.run_worker(
        bridge_root / "tasks" / task_id,
        project=project,
        worker=None,
        bridge_root=bridge_root,
        quiet=True,
    )

    effective_root = Path(captured["project"].project_root)
    expected_root = bridge_root / "runtime" / "worktrees" / task_id
    assert effective_root == expected_root
    assert effective_root.is_dir()
    assert effective_root != project_root
    assert result["workspaceMode"] == "local-worktree"
    assert result["workspacePath"] == str(expected_root)

    branch = subprocess.run(
        ["git", "-C", str(effective_root), "branch", "--show-current"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert branch == f"task/{task_id}"


def test_local_worktree_is_reused_on_retry(tmp_path):
    from bridge.config import ProjectConfig
    from bridge.workspace.local_worktree import LocalWorktreeWorkspace

    project_root = tmp_path / "project"
    bridge_root = tmp_path / "bridge"
    task_dir = bridge_root / "tasks" / "reuse"
    task_dir.mkdir(parents=True)
    _init_git_repo(project_root)

    project = ProjectConfig(
        id="p1", transport="local", project_root=str(project_root)
    )
    manager = LocalWorktreeWorkspace(bridge_root / "runtime" / "worktrees")
    first = manager.prepare(project, "reuse", task_dir)
    second = manager.prepare(project, "reuse", task_dir)

    assert second.repo_path == first.repo_path
    assert second.extra["reused"] is True


def test_ssh_auto_remains_existing_for_compatibility(tmp_path, monkeypatch):
    import bridge.worker as worker_module
    from bridge.application.task_service import create_task
    from bridge.config import ProjectConfig
    from bridge.transport import TransportResult

    bridge_root = tmp_path / "bridge"
    create_task(
        bridge_root=bridge_root, project_id="p1", worker_id=None,
        role="implement", task_id="ssh-auto", task_file=None,
    )
    captured = {}

    class FakeSshTransport:
        def run(self, **kwargs):
            captured.update(kwargs)
            return TransportResult(exit_code=1, stdout="", stderr="")

    monkeypatch.setitem(worker_module.TRANSPORT_MAP, "ssh", FakeSshTransport)
    project = ProjectConfig(
        id="p1", transport="ssh", project_root="/srv/shared",
        ssh_host="example.invalid", remote_bridge_root="/srv/bridge",
    )
    result = worker_module.run_worker(
        bridge_root / "tasks" / "ssh-auto", project, None, bridge_root, quiet=True
    )

    assert captured["project"].project_root == "/srv/shared"
    assert result["workspaceMode"] == "existing"
    assert result["workspacePath"] == "/srv/shared"


def test_explicit_isolation_on_plain_ssh_blocks_before_transport(tmp_path, monkeypatch):
    import bridge.worker as worker_module
    from bridge.application.task_service import create_task
    from bridge.config import ProjectConfig
    from bridge.transport import TransportResult

    bridge_root = tmp_path / "bridge"
    create_task(
        bridge_root=bridge_root, project_id="p1", worker_id=None,
        role="implement", task_id="ssh-isolated", task_file=None,
        workspace="isolated",
    )
    called = {"value": False}

    class FakeSshTransport:
        def run(self, **kwargs):
            called["value"] = True
            return TransportResult(exit_code=0, stdout="", stderr="")

    monkeypatch.setitem(worker_module.TRANSPORT_MAP, "ssh", FakeSshTransport)
    project = ProjectConfig(
        id="p1", transport="ssh", project_root="/srv/shared",
        ssh_host="example.invalid", remote_bridge_root="/srv/bridge",
    )
    result = worker_module.run_worker(
        bridge_root / "tasks" / "ssh-isolated", project, None, bridge_root, quiet=True
    )

    assert called["value"] is False
    assert result["state"] == "BLOCKED"
    assert "does not provide an isolated workspace" in result["message"]
