# AI生成
"""E2E tests for P2-05 pipeline orchestrator."""

from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest
from bridge.pipeline import (
    PipelineState,
    PipelineConfig,
    CycleResult,
    run_pipeline_cycle,
    run_pipeline,
    _load_state,
    _save_state,
    _has_active_tasks,
)


@pytest.fixture
def pipeline_bridge(tmp_path):
    bridge = tmp_path / "bridge"
    (bridge / "tasks").mkdir(parents=True)
    (bridge / "runtime").mkdir(parents=True)
    (bridge / "projects.json").write_text(json.dumps({
        "schemaVersion": 1,
        "defaults": {},
        "projects": []
    }))
    (bridge / "workers.json").write_text(json.dumps({
        "schemaVersion": 1,
        "defaults": {"model": "test", "concurrencyLimit": 1, "enabled": True},
        "workers": []
    }))
    return bridge


class TestPipelineState:
    def test_default_state(self):
        s = PipelineState()
        assert s.cycle_count == 0
        assert s.status == "IDLE"

    def test_round_trip(self):
        s = PipelineState(cycle_count=5, status="RUNNING", total_dispatched=10)
        d = s.to_dict()
        s2 = PipelineState.from_dict(d)
        assert s2.cycle_count == 5
        assert s2.status == "RUNNING"
        assert s2.total_dispatched == 10

    def test_serializes_true_first_pass_rate(self):
        state = PipelineState(first_pass_count=3, total_pass_count=4)
        data = state.to_dict()
        assert data["firstPassRate"] == pytest.approx(0.75)

    def test_load_save(self, pipeline_bridge):
        bridge = pipeline_bridge
        s = PipelineState(cycle_count=3, status="RUNNING")
        _save_state(bridge, s)
        s2 = _load_state(bridge)
        assert s2.cycle_count == 3
        assert s2.status == "RUNNING"

    def test_load_missing(self, pipeline_bridge):
        s = _load_state(pipeline_bridge)
        assert s.cycle_count == 0
        assert s.status == "IDLE"


class TestHasActiveTasks:
    def test_empty_bridge(self, pipeline_bridge):
        assert not _has_active_tasks(pipeline_bridge)

    def test_with_ready_task(self, pipeline_bridge):
        bridge = pipeline_bridge
        task_dir = bridge / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "state.json").write_text(json.dumps({"state": "READY", "status": "READY"}))
        assert _has_active_tasks(bridge)

    def test_with_running_task(self, pipeline_bridge):
        bridge = pipeline_bridge
        task_dir = bridge / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "state.json").write_text(json.dumps({"state": "RUNNING", "status": "RUNNING"}))
        assert _has_active_tasks(bridge)

    def test_with_only_done_tasks(self, pipeline_bridge):
        bridge = pipeline_bridge
        task_dir = bridge / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "state.json").write_text(json.dumps({"state": "DONE", "status": "DONE"}))
        assert not _has_active_tasks(bridge)


class TestRunPipelineCycle:
    def test_empty_bridge_cycle(self, pipeline_bridge):
        bridge = pipeline_bridge
        state = PipelineState()
        config = PipelineConfig(dry_run=True)
        result = run_pipeline_cycle(bridge, state, config)
        assert result.cycle == 1
        assert result.dispatched == 0
        assert result.reviewed == 0
        assert result.integrated == 0
        assert state.status == "IDLE"

    def test_cycle_increments_count(self, pipeline_bridge):
        bridge = pipeline_bridge
        state = PipelineState(cycle_count=5)
        config = PipelineConfig(dry_run=True)
        result = run_pipeline_cycle(bridge, state, config)
        assert result.cycle == 6
        assert state.cycle_count == 6

    def test_state_persisted(self, pipeline_bridge):
        bridge = pipeline_bridge
        state = PipelineState()
        config = PipelineConfig(dry_run=True)
        run_pipeline_cycle(bridge, state, config)
        _save_state(bridge, state)
        loaded = _load_state(bridge)
        assert loaded.cycle_count == state.cycle_count

    def test_first_pass_count_excludes_rework_passes(self, pipeline_bridge, monkeypatch):
        bridge = pipeline_bridge
        for task_id, attempt in (("first-pass", 1), ("reworked", 2)):
            task_dir = bridge / "tasks" / task_id
            task_dir.mkdir(parents=True)
            (task_dir / "state.json").write_text(json.dumps({
                "taskId": task_id,
                "state": "DONE",
                "status": "DONE",
                "attempt": attempt,
            }))

        architect_result = SimpleNamespace(
            reviewed=2,
            passed=2,
            errors=[],
            verdicts=[
                SimpleNamespace(task_id="first-pass", decision="PASS"),
                SimpleNamespace(task_id="reworked", decision="PASS"),
            ],
        )
        monkeypatch.setattr(
            "bridge.pipeline.architect_loop", lambda **kwargs: architect_result
        )
        monkeypatch.setattr(
            "bridge.pipeline.auto_dispatch",
            lambda **kwargs: SimpleNamespace(dispatched=0, errors=[]),
        )
        monkeypatch.setattr(
            "bridge.pipeline.integrate_loop", lambda bridge_root: []
        )
        monkeypatch.setattr(
            "bridge.pipeline.detect_conflict",
            lambda task_id, bridge_root: SimpleNamespace(conflict=False),
        )

        state = PipelineState()
        run_pipeline_cycle(bridge, state, PipelineConfig(dry_run=False))

        assert state.total_pass_count == 2
        assert state.first_pass_count == 1
        assert state.to_dict()["firstPassRate"] == pytest.approx(0.5)

    def test_pass_without_attempt_is_not_first_pass(self, pipeline_bridge, monkeypatch):
        bridge = pipeline_bridge
        task_dir = bridge / "tasks" / "legacy-pass"
        task_dir.mkdir(parents=True)
        (task_dir / "state.json").write_text(json.dumps({
            "taskId": "legacy-pass",
            "state": "DONE",
            "status": "DONE",
        }))

        architect_result = SimpleNamespace(
            reviewed=1,
            passed=1,
            errors=[],
            verdicts=[SimpleNamespace(task_id="legacy-pass", decision="PASS")],
        )
        monkeypatch.setattr(
            "bridge.pipeline.architect_loop", lambda **kwargs: architect_result
        )
        monkeypatch.setattr(
            "bridge.pipeline.auto_dispatch",
            lambda **kwargs: SimpleNamespace(dispatched=0, errors=[]),
        )
        monkeypatch.setattr(
            "bridge.pipeline.integrate_loop", lambda bridge_root: []
        )
        monkeypatch.setattr(
            "bridge.pipeline.detect_conflict",
            lambda task_id, bridge_root: SimpleNamespace(conflict=False),
        )

        state = PipelineState()
        run_pipeline_cycle(bridge, state, PipelineConfig(dry_run=False))

        assert state.total_pass_count == 1
        assert state.first_pass_count == 0
        assert state.to_dict()["firstPassRate"] == 0.0

    def test_integration_counts_only_successes_and_surfaces_failures(
        self, pipeline_bridge, monkeypatch
    ):
        bridge = pipeline_bridge
        monkeypatch.setattr(
            "bridge.pipeline.architect_loop",
            lambda **kwargs: SimpleNamespace(
                reviewed=0, passed=0, errors=[], verdicts=[]
            ),
        )
        monkeypatch.setattr(
            "bridge.pipeline.auto_dispatch",
            lambda **kwargs: SimpleNamespace(dispatched=0, errors=[]),
        )
        monkeypatch.setattr(
            "bridge.pipeline.integrate_loop",
            lambda bridge_root: [
                SimpleNamespace(task_id="ok", success=True, error=""),
                SimpleNamespace(
                    task_id="bad", success=False, error="cherry-pick failed"
                ),
            ],
        )
        monkeypatch.setattr(
            "bridge.pipeline.detect_conflict",
            lambda task_id, bridge_root: SimpleNamespace(conflict=False),
        )

        state = PipelineState()
        result = run_pipeline_cycle(
            bridge, state, PipelineConfig(dry_run=False)
        )

        assert result.integrated == 1
        assert state.total_integrated == 1
        assert result.errors == ["integration bad: cherry-pick failed"]

    def test_failed_integration_can_block_without_fake_integrated_count(
        self, pipeline_bridge, monkeypatch
    ):
        bridge = pipeline_bridge
        monkeypatch.setattr(
            "bridge.pipeline.architect_loop",
            lambda **kwargs: SimpleNamespace(
                reviewed=0, passed=0, errors=[], verdicts=[]
            ),
        )
        monkeypatch.setattr(
            "bridge.pipeline.auto_dispatch",
            lambda **kwargs: SimpleNamespace(dispatched=0, errors=[]),
        )
        monkeypatch.setattr(
            "bridge.pipeline.integrate_loop",
            lambda bridge_root: [
                SimpleNamespace(
                    task_id="bad", success=False, error="verification failed"
                ),
            ],
        )
        monkeypatch.setattr(
            "bridge.pipeline.detect_conflict",
            lambda task_id, bridge_root: SimpleNamespace(conflict=False),
        )

        state = PipelineState()
        result = run_pipeline_cycle(
            bridge, state, PipelineConfig(dry_run=False)
        )

        assert result.integrated == 0
        assert state.total_integrated == 0
        assert result.errors == ["integration bad: verification failed"]
        assert state.status == "BLOCKED"

    def test_dry_run_preview_does_not_pollute_operational_totals(
        self, pipeline_bridge, monkeypatch
    ):
        bridge = pipeline_bridge

        review_dir = bridge / "tasks" / "review-me"
        review_dir.mkdir(parents=True)
        (review_dir / "state.json").write_text(json.dumps({
            "taskId": "review-me",
            "state": "REVIEW_REQUIRED",
            "status": "REVIEW_REQUIRED",
        }))

        done_dir = bridge / "tasks" / "done-task"
        done_dir.mkdir(parents=True)
        (done_dir / "state.json").write_text(json.dumps({
            "taskId": "done-task",
            "state": "DONE",
            "status": "DONE",
        }))

        monkeypatch.setattr(
            "bridge.pipeline.auto_dispatch",
            lambda **kwargs: SimpleNamespace(dispatched=0, errors=[]),
        )
        monkeypatch.setattr(
            "bridge.pipeline.detect_conflict",
            lambda task_id, bridge_root: SimpleNamespace(
                conflict=(task_id == "done-task")
            ),
        )

        state = PipelineState(
            total_reviewed=7,
            total_integrated=5,
            total_conflicts=3,
        )
        result = run_pipeline_cycle(
            bridge, state, PipelineConfig(dry_run=True)
        )

        assert result.reviewed == 1
        assert result.integrated == 1
        assert result.conflicts == 1
        assert state.total_reviewed == 7
        assert state.total_integrated == 5
        assert state.total_conflicts == 3

    def test_cycle_time_positive(self, pipeline_bridge):
        bridge = pipeline_bridge
        state = PipelineState()
        config = PipelineConfig(dry_run=True)
        result = run_pipeline_cycle(bridge, state, config)
        assert result.cycle_time >= 0.0


class TestRunPipeline:
    def test_once_mode(self, pipeline_bridge):
        bridge = pipeline_bridge
        config = PipelineConfig(once=True, dry_run=True)
        run_pipeline(bridge, config)
        state = _load_state(bridge)
        assert state.cycle_count == 1

    def test_once_mode_persists(self, pipeline_bridge):
        bridge = pipeline_bridge
        config = PipelineConfig(once=True, dry_run=True)
        run_pipeline(bridge, config)
        run_pipeline(bridge, config)
        state = _load_state(bridge)
        assert state.cycle_count == 2

    def test_recoverable_on_restart(self, pipeline_bridge):
        bridge = pipeline_bridge
        state = PipelineState(cycle_count=10, status="RUNNING")
        _save_state(bridge, state)
        config = PipelineConfig(once=True, dry_run=True)
        run_pipeline(bridge, config)
        loaded = _load_state(bridge)
        assert loaded.cycle_count == 11


class TestPipelineConfig:
    def test_defaults(self):
        c = PipelineConfig()
        assert c.interval == 10.0
        assert c.max_workers == 4
        assert not c.dry_run
        assert not c.once

    def test_custom(self):
        c = PipelineConfig(interval=5, max_workers=2, dry_run=True, once=True)
        assert c.interval == 5
        assert c.max_workers == 2
        assert c.dry_run
        assert c.once