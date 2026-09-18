# AI生成
"""Cost tracking and optimization for CodeartsBridge.

Tracks token usage, API call costs, and resource utilization
per project/worker/role, with optimization recommendations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .atomic import read_json_or_none


MODEL_PRICING = {
    "huaweicloud-maas/GLM-5.2": {
        "input_per_1k": 0.002,
        "output_per_1k": 0.006,
        "reasoning_per_1k": 0.006,
        "cache_read_per_1k": 0.0005,
        "cache_write_per_1k": 0.002,
    },
    "default": {
        "input_per_1k": 0.003,
        "output_per_1k": 0.006,
        "reasoning_per_1k": 0.006,
        "cache_read_per_1k": 0.001,
        "cache_write_per_1k": 0.003,
    },
}


@dataclass
class CostRecord:
    task_id: str
    project_id: str = ""
    worker_id: str = ""
    role: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0
    estimated_cost: float = 0.0
    timestamp: str = ""


@dataclass
class CostReport:
    total_cost: float = 0.0
    total_tokens: int = 0
    avg_cost_per_task: float = 0.0
    most_expensive_task: str = ""
    by_project: dict[str, float] = field(default_factory=dict)
    by_worker: dict[str, float] = field(default_factory=dict)
    by_role: dict[str, float] = field(default_factory=dict)
    record_count: int = 0


def normalize_tokens(tokens) -> dict:
    """Normalize token payloads from supported runtimes to one canonical shape.

    Supported inputs:
    - scalar total token counts
    - canonical keys: input/output/reasoning/cache.read/cache.write
    - OpenAI-style aliases: input_tokens/output_tokens/reasoning_tokens
    - legacy aliases: prompt_tokens/completion_tokens
    - total-only dicts: total/total_tokens/totalTokens
    """
    empty = {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache": {"read": 0, "write": 0},
    }
    if tokens is None or isinstance(tokens, bool):
        return empty

    if isinstance(tokens, (int, float, str)):
        try:
            total = max(0, int(float(tokens)))
        except (TypeError, ValueError):
            return empty
        return {**empty, "input": total}

    if not isinstance(tokens, dict):
        return empty

    def _number(*keys) -> int:
        for key in keys:
            if key in tokens and tokens.get(key) is not None:
                try:
                    return max(0, int(float(tokens.get(key))))
                except (TypeError, ValueError):
                    continue
        return 0

    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}

    def _cache_number(nested_key: str, *flat_keys: str) -> int:
        value = cache.get(nested_key)
        if value is not None:
            try:
                return max(0, int(float(value)))
            except (TypeError, ValueError):
                pass
        return _number(*flat_keys)

    normalized = {
        "input": _number("input", "input_tokens", "prompt_tokens"),
        "output": _number("output", "output_tokens", "completion_tokens"),
        "reasoning": _number("reasoning", "reasoning_tokens"),
        "cache": {
            "read": _cache_number("read", "cache_read", "cache_read_tokens"),
            "write": _cache_number("write", "cache_write", "cache_write_tokens"),
        },
    }

    if normalized["input"] == normalized["output"] == normalized["reasoning"] == 0:
        total = _number("total", "total_tokens", "totalTokens")
        if total:
            normalized["input"] = total

    return normalized


def token_total(tokens) -> int:
    """Return non-cache input + output + reasoning tokens for reporting."""
    normalized = normalize_tokens(tokens)
    return normalized["input"] + normalized["output"] + normalized["reasoning"]


def _estimate_cost(tokens: dict, model: str) -> float:
    tokens = normalize_tokens(tokens)
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
    cost = 0.0
    cost += tokens["input"] / 1000 * pricing["input_per_1k"]
    cost += tokens["output"] / 1000 * pricing["output_per_1k"]
    cost += tokens["reasoning"] / 1000 * pricing["reasoning_per_1k"]
    cache = tokens["cache"]
    cost += cache["read"] / 1000 * pricing["cache_read_per_1k"]
    cost += cache["write"] / 1000 * pricing["cache_write_per_1k"]
    return round(cost, 6)


def collect_cost_records(bridge_root: Path) -> list[CostRecord]:
    bridge_root = Path(bridge_root)
    tasks_dir = bridge_root / "tasks"
    if not tasks_dir.exists():
        return []

    records = []
    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        state = read_json_or_none(task_dir / "state.json")
        if not state:
            continue
        raw_tokens = state.get("tokens")
        tokens = normalize_tokens(raw_tokens)
        if token_total(tokens) == 0 and tokens["cache"]["read"] == 0 and tokens["cache"]["write"] == 0:
            continue

        meta = read_json_or_none(task_dir / "META.json") or {}
        model = meta.get("model", "huaweicloud-maas/GLM-5.2")
        cost = _estimate_cost(tokens, model)

        records.append(CostRecord(
            task_id=state.get("taskId", task_dir.name),
            project_id=meta.get("projectId", ""),
            worker_id=state.get("assignedWorkerId") or meta.get("workerId", ""),
            role=meta.get("role", ""),
            model=model,
            tokens_in=tokens["input"],
            tokens_out=tokens["output"],
            tokens_reasoning=tokens["reasoning"],
            cache_read=tokens["cache"]["read"],
            cache_write=tokens["cache"]["write"],
            estimated_cost=cost,
            timestamp=state.get("updatedAt", ""),
        ))
    return records


def generate_cost_report(bridge_root: Path) -> CostReport:
    records = collect_cost_records(bridge_root)
    report = CostReport(record_count=len(records))

    if not records:
        return report

    most_expensive = max(records, key=lambda r: r.estimated_cost)
    report.most_expensive_task = most_expensive.task_id

    for r in records:
        report.total_cost += r.estimated_cost
        report.total_tokens += r.tokens_in + r.tokens_out + r.tokens_reasoning

        if r.project_id:
            report.by_project[r.project_id] = report.by_project.get(r.project_id, 0) + r.estimated_cost
        if r.worker_id:
            report.by_worker[r.worker_id] = report.by_worker.get(r.worker_id, 0) + r.estimated_cost
        if r.role:
            report.by_role[r.role] = report.by_role.get(r.role, 0) + r.estimated_cost

    report.avg_cost_per_task = round(report.total_cost / len(records), 6)
    report.total_cost = round(report.total_cost, 6)
    return report


def optimize_recommendations(report: CostReport) -> list[str]:
    recs = []

    if report.record_count == 0:
        recs.append("No cost data available — complete tasks to generate recommendations")
        return recs

    if report.avg_cost_per_task > 0.05:
        recs.append(f"High avg cost per task (${report.avg_cost_per_task:.4f}) — consider caching for repeated prompts")

    for project, cost in sorted(report.by_project.items(), key=lambda x: -x[1]):
        if cost > report.total_cost * 0.5:
            recs.append(f"Project '{project}' accounts for {cost/report.total_cost*100:.0f}% of total cost — review task complexity")

    for worker, cost in sorted(report.by_worker.items(), key=lambda x: -x[1]):
        if cost > report.total_cost * 0.5 and len(report.by_worker) > 1:
            recs.append(f"Worker '{worker}' is the most expensive — consider redistributing tasks")

    cache_savings = sum(1 for p, c in report.by_project.items() if c > 0.01)
    if cache_savings > 0:
        recs.append(f"Enable prompt caching for {cache_savings} project(s) to reduce input token costs")

    if not recs:
        recs.append("Cost distribution looks healthy — no optimization needed")

    return recs


def format_cost_report(bridge_root: Path) -> str:
    report = generate_cost_report(bridge_root)
    recs = optimize_recommendations(report)

    lines = ["=== Cost Report ===", ""]
    lines.append(f"Total cost:          ${report.total_cost:.6f}")
    lines.append(f"Total tokens:        {report.total_tokens:,}")
    lines.append(f"Avg cost per task:   ${report.avg_cost_per_task:.6f}")
    lines.append(f"Most expensive task: {report.most_expensive_task}")
    lines.append(f"Records:             {report.record_count}")
    lines.append("")

    if report.by_project:
        lines.append("--- By Project ---")
        for p, c in sorted(report.by_project.items(), key=lambda x: -x[1]):
            lines.append(f"  {p:<30} ${c:.6f}")
        lines.append("")

    if report.by_worker:
        lines.append("--- By Worker ---")
        for w, c in sorted(report.by_worker.items(), key=lambda x: -x[1]):
            lines.append(f"  {w:<30} ${c:.6f}")
        lines.append("")

    if report.by_role:
        lines.append("--- By Role ---")
        for r, c in sorted(report.by_role.items(), key=lambda x: -x[1]):
            lines.append(f"  {r:<30} ${c:.6f}")
        lines.append("")

    lines.append("--- Recommendations ---")
    for r in recs:
        lines.append(f"  • {r}")

    return "\n".join(lines)