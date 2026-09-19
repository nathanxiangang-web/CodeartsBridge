"""Lifecycle truth regression tests for real integration."""

from __future__ import annotations

import json
import subprocess

from bridge.core.state import APPROVED, DONE, INTEGRATION_FAILED
from bridge.state import get_state, set_state


def _make_approved_task(tmp_path, task_id="t1", commit_sha=None):
    bridge_root = tmp_path / "bridge"
    task_dir = bridge_root / "tasks" / task_id
    (task_dir / "outbox").mkdir(parents=True)
    (task_dir / "META.json").write_text(
        json.dumps({
            "schemaVersion": 2,
            "taskId": task_id,
            "projectId": "p1",
        }),
        encoding="utf-8",
    )
    set_state(task_dir, APPROVED, commit_sha=commit_sha)
    return bridge_root, task_dir


def test_missing_commit_does_not_advance_approved_state(tmp_path):
    from bridge.integration import integrate_task

    bridge_root, task_dir = _make_approved_task(tmp_path)

    result = integrate_task("t1", bridge_root, verify_command=[])

    assert result.success is False
    assert "No result commit SHA found" in result.error
    assert get_state(task_dir)["state"] == APPROVED


def test_dry_run_does_not_mutate_lifecycle_state(tmp_path):
    from bridge.integration import integrate_task

    bridge_root, task_dir = _make_approved_task(
        tmp_path, commit_sha="deadbeef"
    )

    result = integrate_task("t1", bridge_root, dry_run=True, verify_command=[])

    assert result.success is True
    assert result.dry_run is True
    assert get_state(task_dir)["state"] == APPROVED


def test_checkout_failure_converges_to_integration_failed(tmp_path):
    from bridge.integration import integrate_task

    bridge_root, task_dir = _make_approved_task(
        tmp_path, commit_sha="deadbeef"
    )

    # bridge_root is deliberately not a git repository, so checkout fails.
    result = integrate_task("t1", bridge_root, verify_command=[])

    assert result.success is False
    assert "Checkout main failed" in result.error
    assert get_state(task_dir)["state"] == INTEGRATION_FAILED


def test_done_is_never_written_without_integrated_sha(tmp_path, monkeypatch):
    import bridge.integration as integration

    bridge_root, task_dir = _make_approved_task(
        tmp_path, commit_sha="task-commit"
    )

    heads = iter(["pre-merge", "merged-sha"])
    monkeypatch.setattr(integration, "_get_head_sha", lambda _root: next(heads))
    monkeypatch.setattr(
        integration,
        "_run_git",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["git"], returncode=0, stdout="", stderr=""
        ),
    )

    original_set_state = integration.set_state
    done_snapshot = {}

    def recording_set_state(task_dir_arg, status, **kwargs):
        state = original_set_state(task_dir_arg, status, **kwargs)
        if status == DONE:
            done_snapshot.update(state)
        return state

    monkeypatch.setattr(integration, "set_state", recording_set_state)

    result = integration.integrate_task("t1", bridge_root, verify_command=[])

    assert result.success is True
    assert result.merged_sha == "merged-sha"
    assert done_snapshot["state"] == DONE
    assert done_snapshot["integratedSha"] == "merged-sha"
    assert get_state(task_dir)["integratedSha"] == "merged-sha"
