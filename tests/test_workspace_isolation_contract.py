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



def _write_success_deliverables(task_dir: Path) -> None:
    outbox = task_dir / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / "RESULT.md").write_text("# Result\n", encoding="utf-8")
    (outbox / "TESTS.md").write_text("passed: 1\nfailed: 0\n", encoding="utf-8")
    (outbox / "DIFF.stat").write_text("1 file changed\n", encoding="utf-8")


def test_local_worker_persists_isolated_result_commit(tmp_path, monkeypatch):
    import bridge.worker as worker_module
    from bridge.application.task_service import create_task
    from bridge.config import ProjectConfig
    from bridge.transport import TransportResult

    project_root = tmp_path / "project"
    bridge_root = tmp_path / "bridge"
    _init_git_repo(project_root)
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=project_root, check=True, capture_output=True,
    )

    task_id = "commit-capture"
    create_task(
        bridge_root=bridge_root,
        project_id="p1",
        worker_id=None,
        role="implement",
        task_id=task_id,
        task_file=None,
        review_required=False,
    )

    class CommittingTransport:
        def run(self, **kwargs):
            worktree = Path(kwargs["project"].project_root)
            (worktree / "feature.txt").write_text("isolated change\n", encoding="utf-8")
            subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
            subprocess.run(
                ["git", "commit", "-m", "task change"],
                cwd=worktree, check=True, capture_output=True,
            )
            _write_success_deliverables(Path(kwargs["task_dir"]))
            return TransportResult(exit_code=0, stdout="", stderr="")

    monkeypatch.setitem(worker_module.TRANSPORT_MAP, "local", CommittingTransport)
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

    commit_sha = result.get("commitSha")
    assert result["state"] == "DONE"
    assert commit_sha
    assert len(commit_sha) == 40
    commit_file = bridge_root / "tasks" / task_id / "outbox" / "COMMIT.sha"
    assert commit_file.read_text(encoding="utf-8").strip() == commit_sha

    worktree = bridge_root / "runtime" / "worktrees" / task_id
    head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head == commit_sha


def test_remote_import_failure_cannot_reach_review_or_done(tmp_path, monkeypatch):
    import bridge.worker as worker_module
    from bridge.application.task_service import create_task
    from bridge.config import ProjectConfig
    from bridge.transport import TransportResult

    bridge_root = tmp_path / "bridge"
    task_id = "remote-import-fail"
    create_task(
        bridge_root=bridge_root,
        project_id="p1",
        worker_id=None,
        role="implement",
        task_id=task_id,
        task_file=None,
    )

    class BrokenImportTransport:
        def run(self, **kwargs):
            _write_success_deliverables(Path(kwargs["task_dir"]))
            return TransportResult(
                exit_code=0,
                stdout="",
                stderr="",
                import_error="result bundle rejected",
            )

    monkeypatch.setitem(
        worker_module.TRANSPORT_MAP, "remote-worktree", BrokenImportTransport
    )
    project = ProjectConfig(
        id="p1",
        transport="remote-worktree",
        project_root="/srv/source",
        ssh_host="example.invalid",
        remote_workspace_root="/srv/workspaces",
    )

    result = worker_module.run_worker(
        bridge_root / "tasks" / task_id,
        project=project,
        worker=None,
        bridge_root=bridge_root,
        quiet=True,
    )

    assert result["state"] == "FAILED"
    assert "result import failed" in result["message"]
    assert not result.get("commitSha")


def test_integration_uses_result_commit_and_cleans_local_worktree(tmp_path):
    import json

    from bridge.config import ProjectConfig
    from bridge.integration import integrate_task
    from bridge.state import set_state
    from bridge.workspace.local_worktree import LocalWorktreeWorkspace

    project_root = tmp_path / "project"
    bridge_root = tmp_path / "bridge"
    task_id = "integrate-local"

    _init_git_repo(project_root)
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=project_root, check=True, capture_output=True,
    )

    bridge_root.mkdir(parents=True, exist_ok=True)
    (bridge_root / "projects.json").write_text(json.dumps({
        "schemaVersion": 1,
        "defaults": {},
        "projects": [{
            "id": "p1",
            "transport": "local",
            "projectRoot": str(project_root),
        }],
    }), encoding="utf-8")

    task_dir = bridge_root / "tasks" / task_id
    (task_dir / "outbox").mkdir(parents=True)
    (task_dir / "META.json").write_text(json.dumps({
        "schemaVersion": 2,
        "taskId": task_id,
        "projectId": "p1",
        "role": "implement",
        "execution": {"workspace": "auto"},
        "review": {"required": False, "independentWorker": True},
    }), encoding="utf-8")

    project = ProjectConfig(
        id="p1", transport="local", project_root=str(project_root)
    )
    manager = LocalWorktreeWorkspace(bridge_root / "runtime" / "worktrees")
    workspace = manager.prepare(project, task_id, task_dir)

    worktree = Path(workspace.repo_path)
    (worktree / "integrated.txt").write_text("from task\n", encoding="utf-8")
    subprocess.run(["git", "add", "integrated.txt"], cwd=worktree, check=True)
    subprocess.run(
        ["git", "commit", "-m", "isolated task"],
        cwd=worktree, check=True, capture_output=True,
    )
    commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree, capture_output=True, text=True, check=True,
    ).stdout.strip()

    set_state(
        task_dir,
        "APPROVED",
        workspace_mode="local-worktree",
        workspace_path=str(worktree),
        commit_sha=commit_sha,
    )
    (task_dir / "outbox" / "COMMIT.sha").write_text(
        commit_sha + "\n", encoding="utf-8"
    )

    result = integrate_task(
        task_id,
        bridge_root,
        verify_command=[],
        target_branch="main",
    )

    assert result.success is True
    assert result.commit_sha == commit_sha
    assert (project_root / "integrated.txt").read_text(encoding="utf-8") == "from task\n"
    assert not worktree.exists()

    branch_check = subprocess.run(
        ["git", "-C", str(project_root), "show-ref", "--verify", "--quiet",
         f"refs/heads/task/{task_id}"],
        capture_output=True,
    )
    assert branch_check.returncode != 0

    state = json.loads((task_dir / "state.json").read_text(encoding="utf-8"))
    assert state.get("workspaceCleanedAt")
    assert not state.get("workspaceCleanupError")


def test_integration_never_treats_baseline_as_result_commit(tmp_path):
    import json

    from bridge.integration import integrate_task
    from bridge.state import set_state

    project_root = tmp_path / "project"
    bridge_root = tmp_path / "bridge"
    task_id = "baseline-is-not-result"

    _init_git_repo(project_root)
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=project_root, check=True, capture_output=True,
    )
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root, capture_output=True, text=True, check=True,
    ).stdout.strip()

    (bridge_root / "tasks" / task_id / "outbox").mkdir(parents=True)
    task_dir = bridge_root / "tasks" / task_id
    (task_dir / "META.json").write_text(json.dumps({
        "schemaVersion": 2,
        "taskId": task_id,
        "projectId": "p1",
        "baseline": baseline,
    }), encoding="utf-8")
    (bridge_root / "projects.json").write_text(json.dumps({
        "schemaVersion": 1,
        "defaults": {},
        "projects": [{
            "id": "p1",
            "transport": "local",
            "projectRoot": str(project_root),
        }],
    }), encoding="utf-8")
    set_state(task_dir, "APPROVED")

    result = integrate_task(task_id, bridge_root, verify_command=[])

    assert result.success is False
    assert "No result commit SHA found" in result.error
