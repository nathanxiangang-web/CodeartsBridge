# AI生成
"""E2E tests for P1-02: priority, estimated duration and critical-path scheduling."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from bridge.scheduler.priority import (
    SchedulingMeta, ScheduledTask,
    build_scheduled_task, sort_by_critical_path,
    select_worker, plan_dispatch,
)
from bridge.config import WorkerConfig


def _make_task(tid, priority=50, est=0, attempt=1, max_retries=1,
               deps=None, dep_states=None, preferred=None, resource="implementation"):
    return ScheduledTask(
        task_id=tid, priority=priority, estimated_minutes=est,
        attempt=attempt, max_retries=max_retries,
        preferred_workers=preferred or [], resource_class=resource,
        dependencies=deps or [], dependency_states=dep_states or {},
    )


class TestSchedulingMeta:
    def test_defaults(self):
        m = SchedulingMeta.from_meta({})
        assert m.priority == 50
        assert m.estimated_minutes == 0.0
        assert m.max_retries == 1
        assert m.resource_class == "implementation"

    def test_from_meta(self):
        m = SchedulingMeta.from_meta({
            "priority": 90, "estimatedMinutes": 15,
            "maxRetries": 3, "preferredWorkers": ["w1"],
            "resourceClass": "review",
        })
        assert m.priority == 90
        assert m.estimated_minutes == 15
        assert m.max_retries == 3
        assert m.preferred_workers == ["w1"]
        assert m.resource_class == "review"


class TestScheduledTask:
    def test_deps_done(self):
        t = _make_task("t1", dep_states={"d1": "DONE", "d2": "DONE"})
        assert t.deps_done is True

    def test_deps_not_done(self):
        t = _make_task("t1", dep_states={"d1": "DONE", "d2": "RUNNING"})
        assert t.deps_done is False
        assert t.deps_pending == 1

    def test_can_retry(self):
        t = _make_task("t1", attempt=2, max_retries=3)
        assert t.can_retry is True

    def test_cannot_retry(self):
        t = _make_task("t1", attempt=4, max_retries=3)
        assert t.can_retry is False

    def test_scheduling_score_higher_priority(self):
        t1 = _make_task("t1", priority=90)
        t2 = _make_task("t2", priority=10)
        assert t1.scheduling_score > t2.scheduling_score

    def test_scheduling_score_deps_penalty(self):
        t1 = _make_task("t1", dep_states={})
        t2 = _make_task("t2", dep_states={"d1": "RUNNING"})
        assert t1.scheduling_score > t2.scheduling_score


class TestSortByCriticalPath:
    def test_ready_before_blocked(self):
        t1 = _make_task("t1", dep_states={})
        t2 = _make_task("t2", dep_states={"d1": "RUNNING"})
        result = sort_by_critical_path([t2, t1])
        assert result[0].task_id == "t1"
        assert result[1].task_id == "t2"

    def test_higher_priority_first(self):
        t1 = _make_task("t1", priority=90)
        t2 = _make_task("t2", priority=10)
        result = sort_by_critical_path([t2, t1])
        assert result[0].task_id == "t1"

    def test_exhausted_retries_last(self):
        t1 = _make_task("t1", attempt=1, max_retries=1)
        t2 = _make_task("t2", attempt=2, max_retries=1)
        result = sort_by_critical_path([t2, t1])
        assert result[-1].task_id == "t2"


class TestSelectWorker:
    def test_preferred_worker(self):
        w1 = WorkerConfig(id="w1", transport="local")
        w2 = WorkerConfig(id="w2", transport="local")
        task = _make_task("t1", preferred=["w2"])
        selected = select_worker(task, [w1, w2], {})
        assert selected.id == "w2"

    def test_capability_match(self):
        w1 = WorkerConfig(id="w1", transport="local", capabilities=["implement"])
        w2 = WorkerConfig(id="w2", transport="local", capabilities=["review"])
        task = _make_task("t1", resource="review")
        selected = select_worker(task, [w1, w2], {})
        assert selected.id == "w2"

    def test_concurrency_limit(self):
        w1 = WorkerConfig(id="w1", transport="local", concurrency_limit=1)
        task = _make_task("t1")
        selected = select_worker(task, [w1], {"w1": 1})
        assert selected is None

    def test_disabled_worker(self):
        w1 = WorkerConfig(id="w1", transport="local", enabled=False)
        task = _make_task("t1")
        selected = select_worker(task, [w1], {})
        assert selected is None

    def test_no_workers(self):
        task = _make_task("t1")
        selected = select_worker(task, [], {})
        assert selected is None


class TestPlanDispatch:
    def test_basic_plan(self):
        w1 = WorkerConfig(id="w1", transport="local", concurrency_limit=2)
        t1 = _make_task("t1", priority=90)
        t2 = _make_task("t2", priority=10)
        plan = plan_dispatch([t1, t2], [w1], {})
        assert len(plan) == 2
        assert plan[0][0] == "t1"

    def test_blocked_task_not_scheduled(self):
        w1 = WorkerConfig(id="w1", transport="local")
        t1 = _make_task("t1", dep_states={"d1": "RUNNING"})
        plan = plan_dispatch([t1], [w1], {})
        assert len(plan) == 0

    def test_concurrency_respected(self):
        w1 = WorkerConfig(id="w1", transport="local", concurrency_limit=1)
        t1 = _make_task("t1")
        t2 = _make_task("t2")
        plan = plan_dispatch([t1, t2], [w1], {})
        assert len(plan) == 1

    def test_multiple_workers(self):
        w1 = WorkerConfig(id="w1", transport="local")
        w2 = WorkerConfig(id="w2", transport="local")
        t1 = _make_task("t1")
        t2 = _make_task("t2")
        plan = plan_dispatch([t1, t2], [w1, w2], {})
        assert len(plan) == 2

    def test_exhausted_retries_not_scheduled(self):
        w1 = WorkerConfig(id="w1", transport="local")
        t1 = _make_task("t1", attempt=2, max_retries=1)
        plan = plan_dispatch([t1], [w1], {})
        assert len(plan) == 0