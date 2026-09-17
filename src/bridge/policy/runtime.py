# AI生成
"""Policy runtime: evaluate phases, checks, and approval gates.

Mirrors PowerShell Bridge.PolicyRuntime.psm1.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import Profile, Phase, Check


@dataclass
class CheckResult:
    check_id: str
    passed: bool
    exit_code: int | None = None
    message: str = ""
    evidence_found: dict[str, bool] | None = None


@dataclass
class PhaseResult:
    phase_id: str
    passed: bool
    check_results: list[CheckResult] = None
    approval_required: bool = False
    message: str = ""


def evaluate_check(
    check: Check,
    task_dir: str | Path,
    project_root: str | Path,
    env: dict[str, str] | None = None,
) -> CheckResult:
    """Evaluate a single check: run command, verify exit code and evidence."""
    if check.skip:
        return CheckResult(check_id=check.id, passed=True, message="skipped")

    if not check.command:
        return CheckResult(check_id=check.id, passed=True, message="no command")

    cmd = check.command
    executable = cmd.get("executable", "")
    argv = cmd.get("argv", [])
    if not executable:
        return CheckResult(check_id=check.id, passed=False, message="missing executable")

    # Run command
    try:
        r = subprocess.run(
            [executable] + argv,
            capture_output=True,
            text=True,
            timeout=check.timeout_seconds or 60,
            cwd=str(project_root),
            env=env,
        )
        exit_code = r.returncode
    except subprocess.TimeoutExpired:
        return CheckResult(check_id=check.id, passed=False, message="timeout")
    except Exception as e:
        return CheckResult(check_id=check.id, passed=False, message=str(e))

    # Check exit code
    expected = check.expect_exit_code
    if exit_code != expected:
        return CheckResult(
            check_id=check.id, passed=False, exit_code=exit_code,
            message=f"exit code {exit_code} != expected {expected}",
        )

    # Check required evidence
    evidence_found = {}
    for evidence in check.required_evidence:
        p = Path(task_dir) / "outbox" / evidence
        evidence_found[evidence] = p.is_file()

    all_evidence = all(evidence_found.values()) if evidence_found else True
    if not all_evidence:
        missing = [k for k, v in evidence_found.items() if not v]
        return CheckResult(
            check_id=check.id, passed=False, exit_code=exit_code,
            message=f"missing evidence: {missing}",
            evidence_found=evidence_found,
        )

    return CheckResult(
        check_id=check.id, passed=True, exit_code=exit_code,
        evidence_found=evidence_found,
    )


def evaluate_phase(
    phase: Phase,
    task_dir: str | Path,
    project_root: str | Path,
    role: str = "implement",
    env: dict[str, str] | None = None,
) -> PhaseResult:
    """Evaluate all checks in a phase for a given role."""
    from .engine import PolicyEngine

    checks = PolicyEngine.select_checks_for_role(phase, role)
    results = [evaluate_check(c, task_dir, project_root, env) for c in checks]

    # Also evaluate finally checks
    for fc in phase.finally_checks:
        if fc.skip or (fc.roles and role not in fc.roles):
            continue
        results.append(evaluate_check(fc, task_dir, project_root, env))

    all_passed = all(r.passed for r in results)
    approval_required = phase.requires_approval and all_passed

    return PhaseResult(
        phase_id=phase.id,
        passed=all_passed,
        check_results=results,
        approval_required=approval_required,
    )


def find_unmet_approval(profile: Profile, phase_results: list[PhaseResult]) -> str | None:
    """Find the first phase that requires approval but hasn't been approved."""
    for pr in phase_results:
        if pr.approval_required:
            phase = next((p for p in profile.phases if p.id == pr.phase_id), None)
            if phase and phase.approval_gate:
                return phase.approval_gate
    return None