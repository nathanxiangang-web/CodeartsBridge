# AI生成
"""Policy integration into the execution chain.

Connects the policy engine to the runtime supervisor, running phase
gates and checks at the appropriate points in the task lifecycle:
- Pre-execution: validate policy profile exists
- Post-execution: run phase checks, evaluate approval gates
- On failure: apply on-failure mode (block/continue/warn)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engine import PolicyEngine, Profile, Phase, Check
from .runtime import (
    evaluate_check, evaluate_phase, find_unmet_approval,
    CheckResult, PhaseResult,
)

logger = logging.getLogger(__name__)


@dataclass
class PolicyEvaluationResult:
    """Result of evaluating all policy phases for a task."""
    passed: bool
    phase_results: list[PhaseResult] = field(default_factory=list)
    approval_gate: str | None = None
    blocked: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def load_profile_for_project(
    config_dir: Path,
    project_id: str,
    profile_name: str = "default",
) -> Profile | None:
    """Load a policy profile for a project. Returns None if no profile exists."""
    profile_path = Path(config_dir) / "policies" / f"{profile_name}.json"
    if not profile_path.is_file():
        return None
    try:
        return PolicyEngine.load_profile(profile_path)
    except (ValueError, OSError) as e:
        logger.warning("Failed to load policy profile %s: %s", profile_path, e)
        return None


def evaluate_pre_checks(
    profile: Profile,
    task_dir: Path,
    project_root: Path,
    role: str = "implement",
    env: dict[str, str] | None = None,
) -> PolicyEvaluationResult:
    """Evaluate pre-execution checks (phase.id == 'preCheck').

    Runs before the worker starts. If any preCheck phase with onFailure=block
    fails, the task should be BLOCKED and not dispatched to the worker.
    """
    phases = PolicyEngine.select_phases_for_role(profile, role)
    pre_phases = [p for p in phases if p.id == "pre-check"]
    phase_results: list[PhaseResult] = []
    warnings: list[str] = []
    errors: list[str] = []
    blocked = False

    for phase in pre_phases:
        result = evaluate_phase(phase, task_dir, project_root, role, env)
        phase_results.append(result)
        if not result.passed:
            if phase.on_failure == "block":
                blocked = True
                errors.append(f"PreCheck phase '{phase.id}' failed (onFailure=block)")
            elif phase.on_failure == "warn":
                warnings.append(f"PreCheck phase '{phase.id}' failed (onFailure=warn)")

    all_passed = all(r.passed for r in phase_results) if phase_results else True
    return PolicyEvaluationResult(
        passed=all_passed and not blocked,
        phase_results=phase_results,
        blocked=blocked,
        warnings=warnings,
        errors=errors,
    )


def evaluate_task_policy(
    profile: Profile,
    task_dir: Path,
    project_root: Path,
    role: str = "implement",
    env: dict[str, str] | None = None,
) -> PolicyEvaluationResult:
    """Evaluate all policy phases for a completed task.

    This runs after the worker finishes execution, before review.
    PreCheck phases (id == 'preCheck') are skipped here since they run pre-execution.
    """
    phases = PolicyEngine.select_phases_for_role(profile, role)
    post_phases = [p for p in phases if p.id != "pre-check"]
    phase_results: list[PhaseResult] = []
    warnings: list[str] = []
    errors: list[str] = []
    blocked = False

    for phase in post_phases:
        result = evaluate_phase(phase, task_dir, project_root, role, env)
        phase_results.append(result)

        if not result.passed:
            if phase.on_failure == "block":
                blocked = True
                errors.append(
                    f"Phase '{phase.id}' failed (onFailure=block)"
                )
            elif phase.on_failure == "warn":
                warnings.append(
                    f"Phase '{phase.id}' failed (onFailure=warn)"
                )
            # continue mode: no action

        if result.approval_required:
            logger.info(
                "Phase '%s' requires approval gate: %s",
                phase.id, phase.approval_gate,
            )

    approval_gate = find_unmet_approval(profile, phase_results)
    all_passed = all(r.passed for r in phase_results)

    return PolicyEvaluationResult(
        passed=all_passed and not blocked,
        phase_results=phase_results,
        approval_gate=approval_gate,
        blocked=blocked,
        warnings=warnings,
        errors=errors,
    )


def should_transition_to_review(
    policy_result: PolicyEvaluationResult,
) -> bool:
    """Determine if a task should transition to REVIEW_REQUIRED."""
    if policy_result.blocked:
        return False
    if policy_result.approval_gate:
        return False  # Needs approval first
    return policy_result.passed


def should_block_task(
    policy_result: PolicyEvaluationResult,
) -> bool:
    """Determine if a task should be blocked due to policy violations."""
    return policy_result.blocked
