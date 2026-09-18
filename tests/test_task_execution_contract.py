"""Execution-contract regression tests across TaskService and Worker runtime."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_worker_uses_nested_v2_execution_timeouts(tmp_path, monkeypatch):
    import bridge.worker as worker_module
    from bridge.application.task_service import create_task
    from bridge.config import ProjectConfig
    from bridge.transport import TransportResult

    task_dir = tmp_path / "tasks" / "runtime-contract"
    create_task(
        bridge_root=tmp_path,
        project_id="p1",
        worker_id=None,
        role="implement",
        task_id="runtime-contract",
        task_file=None,
        baseline="baseline-sha",
        workspace="existing",
        target_minutes=7,
        soft_timeout_minutes=9,
        hard_timeout_minutes=11,
    )

    captured = {}

    class FakeTransport:
        def run(self, **kwargs):
            captured.update(kwargs)
            return TransportResult(exit_code=1, stdout="", stderr="")

    monkeypatch.setitem(worker_module.TRANSPORT_MAP, "local", FakeTransport)

    project = ProjectConfig(
        id="p1",
        transport="local",
        project_root=str(tmp_path),
    )

    result = worker_module.run_worker(
        task_dir,
        project=project,
        worker=None,
        bridge_root=tmp_path,
        quiet=True,
    )

    assert result["state"] == "FAILED"
    assert captured["timeout_seconds"] == 11 * 60
    assert captured["soft_timeout_seconds"] == 9 * 60
    assert captured["baseline"] == "baseline-sha"


def test_task_service_defaults_match_v2_task_model(tmp_path):
    import json
    from bridge.application.task_service import create_task

    create_task(
        bridge_root=tmp_path,
        project_id="p1",
        worker_id=None,
        role="implement",
        task_id="defaults",
        task_file=None,
    )

    meta = json.loads(
        (tmp_path / "tasks" / "defaults" / "META.json").read_text(encoding="utf-8")
    )
    assert meta["priority"] == 50
    assert meta["execution"]["workspace"] == "auto"
    assert meta["execution"]["targetMinutes"] == 10
    assert meta["execution"]["softTimeoutMinutes"] == 12
    assert meta["execution"]["hardTimeoutMinutes"] == 15
