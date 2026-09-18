# AI生成
"""E2E tests for P3-02 cost tracking and optimization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bridge.cost import (
    CostRecord, CostReport, MODEL_PRICING,
    collect_cost_records, generate_cost_report,
    optimize_recommendations, format_cost_report,
    _estimate_cost, normalize_tokens, token_total,
)


@pytest.fixture
def cost_bridge(tmp_path):
    bridge = tmp_path / "bridge"
    (bridge / "tasks").mkdir(parents=True)
    return bridge


def _create_task_with_tokens(bridge: Path, task_id: str, tokens: dict, project="p1", worker="w1", role="implement"):
    task_dir = bridge / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "META.json").write_text(json.dumps({
        "taskId": task_id, "projectId": project, "workerId": worker,
        "role": role, "model": "huaweicloud-maas/GLM-5.2",
    }))
    (task_dir / "state.json").write_text(json.dumps({
        "taskId": task_id, "tokens": tokens, "updatedAt": "2026-01-01T00:00:00Z",
    }))


class TestEstimateCost:
    def test_basic_cost(self):
        tokens = {"input": 1000, "output": 500, "reasoning": 200, "cache": {"read": 0, "write": 0}}
        cost = _estimate_cost(tokens, "huaweicloud-maas/GLM-5.2")
        assert cost > 0

    def test_zero_tokens(self):
        cost = _estimate_cost({}, "huaweicloud-maas/GLM-5.2")
        assert cost == 0.0

    def test_cache_discount(self):
        no_cache = {"input": 10000, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        with_cache = {"input": 2000, "output": 0, "reasoning": 0, "cache": {"read": 8000, "write": 0}}
        cost_no = _estimate_cost(no_cache, "huaweicloud-maas/GLM-5.2")
        cost_with = _estimate_cost(with_cache, "huaweicloud-maas/GLM-5.2")
        assert cost_with < cost_no

    def test_normalizes_alias_and_scalar_token_payloads(self):
        aliases = {
            "input_tokens": 120,
            "output_tokens": 80,
            "reasoning_tokens": 50,
            "cache_read_tokens": 20,
        }
        normalized = normalize_tokens(aliases)
        assert normalized["input"] == 120
        assert normalized["output"] == 80
        assert normalized["reasoning"] == 50
        assert normalized["cache"]["read"] == 20
        assert token_total(aliases) == 250
        assert token_total(300) == 300
        assert _estimate_cost(aliases, "huaweicloud-maas/GLM-5.2") > 0
        assert _estimate_cost(300, "huaweicloud-maas/GLM-5.2") > 0

    def test_unknown_model_uses_default(self):
        tokens = {"input": 1000, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        cost = _estimate_cost(tokens, "unknown-model")
        assert cost > 0


class TestCollectCostRecords:
    def test_empty_bridge(self, cost_bridge):
        assert collect_cost_records(cost_bridge) == []

    def test_collects_records(self, cost_bridge):
        _create_task_with_tokens(cost_bridge, "t1", {"input": 100, "output": 50, "reasoning": 10, "cache": {"read": 0, "write": 0}})
        records = collect_cost_records(cost_bridge)
        assert len(records) == 1
        assert records[0].task_id == "t1"
        assert records[0].tokens_in == 100

    def test_collects_alias_tokens_and_runtime_worker(self, cost_bridge):
        _create_task_with_tokens(
            cost_bridge,
            "t-runtime",
            {"input_tokens": 100, "output_tokens": 50, "reasoning_tokens": 25},
            worker="requested-worker",
        )
        state_path = cost_bridge / "tasks" / "t-runtime" / "state.json"
        state = json.loads(state_path.read_text())
        state["assignedWorkerId"] = "runtime-worker"
        state_path.write_text(json.dumps(state))

        records = collect_cost_records(cost_bridge)
        assert len(records) == 1
        assert records[0].worker_id == "runtime-worker"
        assert records[0].tokens_in == 100
        assert records[0].tokens_out == 50
        assert records[0].tokens_reasoning == 25

    def test_collects_scalar_total_tokens(self, cost_bridge):
        _create_task_with_tokens(cost_bridge, "t-scalar", 300)
        records = collect_cost_records(cost_bridge)
        assert len(records) == 1
        assert records[0].tokens_in == 300
        assert records[0].estimated_cost > 0

    def test_skips_tasks_without_tokens(self, cost_bridge):
        task_dir = cost_bridge / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "state.json").write_text(json.dumps({"taskId": "t1"}))
        (task_dir / "META.json").write_text(json.dumps({"taskId": "t1"}))
        assert collect_cost_records(cost_bridge) == []


class TestCostReport:
    def test_empty_report(self, cost_bridge):
        report = generate_cost_report(cost_bridge)
        assert report.total_cost == 0.0
        assert report.record_count == 0

    def test_aggregation(self, cost_bridge):
        _create_task_with_tokens(cost_bridge, "t1", {"input": 1000, "output": 500, "reasoning": 0, "cache": {"read": 0, "write": 0}}, project="A", worker="w1")
        _create_task_with_tokens(cost_bridge, "t2", {"input": 2000, "output": 100, "reasoning": 0, "cache": {"read": 0, "write": 0}}, project="B", worker="w2")
        report = generate_cost_report(cost_bridge)
        assert report.record_count == 2
        assert report.total_cost > 0
        assert "A" in report.by_project
        assert "B" in report.by_project
        assert "w1" in report.by_worker
        assert "w2" in report.by_worker

    def test_most_expensive(self, cost_bridge):
        _create_task_with_tokens(cost_bridge, "cheap", {"input": 10, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}})
        _create_task_with_tokens(cost_bridge, "expensive", {"input": 100000, "output": 50000, "reasoning": 10000, "cache": {"read": 0, "write": 0}})
        report = generate_cost_report(cost_bridge)
        assert report.most_expensive_task == "expensive"


class TestOptimizeRecommendations:
    def test_empty_report(self):
        report = CostReport()
        recs = optimize_recommendations(report)
        assert len(recs) == 1
        assert "No cost data" in recs[0]

    def test_high_cost_warning(self):
        report = CostReport(avg_cost_per_task=0.1, total_cost=1.0, record_count=10)
        recs = optimize_recommendations(report)
        assert any("High" in r for r in recs)

    def test_healthy_report(self):
        report = CostReport(avg_cost_per_task=0.001, total_cost=0.01, record_count=10,
                           by_project={"p1": 0.005}, by_worker={"w1": 0.005})
        recs = optimize_recommendations(report)
        assert any("healthy" in r.lower() for r in recs)


class TestFormatReport:
    def test_format_output(self, cost_bridge):
        _create_task_with_tokens(cost_bridge, "t1", {"input": 100, "output": 50, "reasoning": 10, "cache": {"read": 0, "write": 0}})
        text = format_cost_report(cost_bridge)
        assert "Cost Report" in text
        assert "Recommendations" in text