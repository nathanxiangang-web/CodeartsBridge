"""Regression tests for shared task-state coherence and review policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_core_transition_keeps_state_and_status_in_lockstep(tmp_path):
    from bridge.core.state import set_state, CREATED, READY
    from bridge.state import get_state as get_legacy_state

    task_dir = tmp_path / "tasks" / "sync"
    task_dir.mkdir(parents=True)

    set_state(task_dir, CREATED)
    set_state(task_dir, READY, status="STALE-SHOULD-NOT-WIN")

    raw = json.loads((task_dir / "state.json").read_text(encoding="utf-8"))
    assert raw["state"] == READY
    assert raw["status"] == READY

    legacy = get_legacy_state(task_dir)
    assert legacy["state"] == READY
    assert legacy["status"] == READY


def test_readers_normalize_existing_state_status_drift(tmp_path):
    from bridge.core.state import get_state as get_core_state
    from bridge.state import get_state as get_legacy_state

    task_dir = tmp_path / "tasks" / "drifted"
    task_dir.mkdir(parents=True)
    (task_dir / "state.json").write_text(json.dumps({
        "state": "APPROVED",
        "status": "REVIEW_REQUIRED",
        "attempt": 2,
    }), encoding="utf-8")

    core = get_core_state(task_dir)
    legacy = get_legacy_state(task_dir)

    assert core["state"] == "APPROVED"
    assert core["status"] == "APPROVED"
    assert legacy["state"] == "APPROVED"
    assert legacy["status"] == "APPROVED"
    assert legacy["attempt"] == 2


def test_review_service_transition_is_visible_to_legacy_runtime(tmp_path):
    from bridge.application.review_service import review_pass
    from bridge.state import set_state as set_legacy_state, get_state as get_legacy_state

    task_dir = tmp_path / "tasks" / "review-sync"
    (task_dir / "outbox").mkdir(parents=True)
    set_legacy_state(task_dir, "REVIEW_REQUIRED")

    result = review_pass(tmp_path, "review-sync", reviewer_id="w-review")

    assert result.success is True
    state = get_legacy_state(task_dir)
    assert state["state"] == "APPROVED"
    assert state["status"] == "APPROVED"


def _run_successful_worker(tmp_path, monkeypatch, task_id: str, review_required: bool):
    import bridge.worker as worker_module
    from bridge.application.task_service import create_task
    from bridge.config import ProjectConfig
    from bridge.transport import TransportResult

    task_dir = tmp_path / "tasks" / task_id
    create_task(
        bridge_root=tmp_path,
        project_id="p1",
        worker_id=None,
        role="implement",
        task_id=task_id,
        task_file=None,
        workspace="existing",
        review_required=review_required,
    )

    class SuccessfulTransport:
        def run(self, **kwargs):
            outbox = Path(kwargs["task_dir"]) / "outbox"
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / "RESULT.md").write_text("# Result\n", encoding="utf-8")
            (outbox / "TESTS.md").write_text("passed: 1\nfailed: 0\n", encoding="utf-8")
            (outbox / "DIFF.stat").write_text("1 file changed\n", encoding="utf-8")
            return TransportResult(exit_code=0, stdout="", stderr="")

    monkeypatch.setitem(worker_module.TRANSPORT_MAP, "local", SuccessfulTransport)

    project = ProjectConfig(
        id="p1",
        transport="local",
        project_root=str(tmp_path),
    )
    return worker_module.run_worker(
        task_dir,
        project=project,
        worker=None,
        bridge_root=tmp_path,
        quiet=True,
    )


def test_worker_skips_review_when_task_disables_review(tmp_path, monkeypatch):
    result = _run_successful_worker(
        tmp_path, monkeypatch, "no-review", review_required=False
    )
    assert result["state"] == "DONE"
    assert result["status"] == "DONE"
    assert result["message"] == "deliverables complete; review skipped"


def test_worker_still_requires_review_by_default(tmp_path, monkeypatch):
    result = _run_successful_worker(
        tmp_path, monkeypatch, "needs-review", review_required=True
    )
    assert result["state"] == "REVIEW_REQUIRED"
    assert result["status"] == "REVIEW_REQUIRED"
