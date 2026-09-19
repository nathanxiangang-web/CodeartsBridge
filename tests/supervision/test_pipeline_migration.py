# Tests for AR-03 pipeline migration: supervision + reactor integration.

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from bridge.pipeline import PipelineConfig, PipelineState, run_pipeline_cycle
from bridge.supervision.config import SupervisionConfig
from bridge.supervision.model import ArchitectEvent


class FakeSupervisor:
    def __init__(self, events=None):
        self.tick_calls = 0
        self._events = list(events or [])

    def tick(self, now_monotonic, now_wallclock):
        self.tick_calls += 1
        return list(self._events)


class FakeReactor:
    def __init__(self, batch_result=2):
        self.process_batch_calls = 0
        self._batch_result = batch_result

    def process_batch(self, max_events=10):
        self.process_batch_calls += 1
        return self._batch_result


def _make_bridge_root(tmp_path):
    bridge_root = tmp_path / "bridge"
    (bridge_root / "tasks").mkdir(parents=True)
    return bridge_root


def _config(supervision_config, supervisor=None, reactor=None, dry_run=True):
    return PipelineConfig(
        dry_run=dry_run,
        supervision_config=supervision_config,
        supervisor=supervisor,
        reactor=reactor,
    )


def test_supervision_disabled_skips_tick(tmp_path):
    bridge_root = _make_bridge_root(tmp_path)
    sup = FakeSupervisor()
    cfg = _config(SupervisionConfig(supervisionEnabled=False), supervisor=sup)

    result = run_pipeline_cycle(bridge_root, PipelineState(), cfg)

    assert result.supervision_tick_called is False
    assert sup.tick_calls == 0


def test_supervision_enabled_calls_tick(tmp_path):
    bridge_root = _make_bridge_root(tmp_path)
    sup = FakeSupervisor()
    cfg = _config(SupervisionConfig(supervisionEnabled=True), supervisor=sup)

    result = run_pipeline_cycle(bridge_root, PipelineState(), cfg)

    assert result.supervision_tick_called is True
    assert sup.tick_calls == 1


def test_both_review_modes_coexist(tmp_path):
    bridge_root = _make_bridge_root(tmp_path)
    from bridge.state import REVIEW_REQUIRED, set_state
    task_dir = bridge_root / "tasks" / "t1"
    task_dir.mkdir()
    set_state(task_dir, REVIEW_REQUIRED)

    reactor = FakeReactor(batch_result=3)
    cfg = _config(
        SupervisionConfig(
            supervisionEnabled=False,
            architectPollingReview=True,
            architectEventReview=True,
        ),
        reactor=reactor,
    )

    result = run_pipeline_cycle(bridge_root, PipelineState(), cfg)

    assert result.reviewed == 1
    assert reactor.process_batch_calls == 1
    assert result.reactor_processed == 3


def test_shadow_mode_no_state_change(tmp_path):
    bridge_root = _make_bridge_root(tmp_path)
    alert = ArchitectEvent(
        task_id="t1",
        event_type="alert",
        stage=2,
        summary="no progress",
        payload={"noProgressCount": 2},
    )
    sup = FakeSupervisor(events=[alert])
    cfg = _config(
        SupervisionConfig(
            supervisionEnabled=True,
            supervisionShadowMode=True,
            architectEventReview=False,
            architectPollingReview=False,
        ),
        supervisor=sup,
    )

    result = run_pipeline_cycle(bridge_root, PipelineState(), cfg)

    assert result.supervision_tick_called is True
    assert sup.tick_calls == 1
    assert len(result.supervision_events) == 1
    assert result.supervision_events[0].event_type == "alert"
    assert result.reactor_processed == 0
    sup_errors = [e for e in result.errors if "supervisor" in e]
    assert sup_errors == []
