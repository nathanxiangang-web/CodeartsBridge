# AI生成
"""E2E tests for P2-05 pipeline orchestrator."""

from __future__ import annotations

import json
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