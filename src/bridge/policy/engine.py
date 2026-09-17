# AI生成
"""Policy engine: load/validate profiles, select gates for role/phase.

Mirrors PowerShell Bridge.Policy.psm1.
Project-agnostic, pure, testable. No third-party dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..atomic import read_json

SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SAFE_ROLE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
SAFE_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_SECRET_REF_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
RISK_LEVELS = ("low", "medium", "high", "critical")
ON_FAILURE_MODES = ("block", "continue", "warn")
WD_MODES = ("projectRoot", "subpath", "temp")

ALLOWED_PROFILE_KEYS = {
    "schemaVersion", "profileId", "projectId", "description", "riskLevel",
    "roles", "defaultTimeoutSeconds", "workingDirectory", "phases",
}
ALLOWED_PHASE_KEYS = {
    "id", "description", "roles", "riskLevel", "requiresApproval",
    "approvalGate", "timeoutSeconds", "onFailure", "checks", "finallyChecks",
}
ALLOWED_CHECK_KEYS = {
    "id", "description", "roles", "riskLevel", "timeoutSeconds",
    "command", "requiredEvidence", "expectExitCode", "skip",
}
ALLOWED_COMMAND_KEYS = {"executable", "argv", "env", "workingDirectory"}


@dataclass
class Check:
    id: str
    description: str = ""
    roles: list[str] = field(default_factory=list)
    risk_level: str = "low"
    timeout_seconds: int | None = None
    command: dict | None = None
    required_evidence: list[str] = field(default_factory=list)
    expect_exit_code: int = 0
    skip: bool = False


@dataclass
class Phase:
    id: str
    description: str = ""
    roles: list[str] = field(default_factory=list)
    risk_level: str = "low"
    requires_approval: bool = False
    approval_gate: str | None = None
    timeout_seconds: int | None = None
    on_failure: str = "block"
    checks: list[Check] = field(default_factory=list)
    finally_checks: list[Check] = field(default_factory=list)


@dataclass
class Profile:
    schema_version: int
    profile_id: str
    project_id: str
    description: str = ""
    risk_level: str = "low"
    roles: list[str] = field(default_factory=list)
    default_timeout_seconds: int = 300
    working_directory: dict | None = None
    phases: list[Phase] = field(default_factory=list)


class PolicyEngine:
    """Load and validate policy profiles."""

    @staticmethod
    def load_profile(path: str | Path) -> Profile:
        data = read_json(path)
        issues: list[str] = []
        profile = PolicyEngine._validate_profile(data, issues)
        if issues:
            raise ValueError(f"Profile validation failed: {'; '.join(issues)}")
        return profile

    @staticmethod
    def _validate_profile(data: dict, issues: list[str]) -> Profile:
        # Check unknown keys
        for k in data:
            if k not in ALLOWED_PROFILE_KEYS:
                issues.append(f"Unknown field '{k}' at profile root.")

        profile_id = data.get("profileId", "")
        if not profile_id or not SAFE_ID_RE.match(profile_id):
            issues.append(f"profileId does not match {SAFE_ID_RE.pattern}: {profile_id}")

        project_id = data.get("projectId", "")
        if not project_id or not SAFE_ID_RE.match(project_id):
            issues.append(f"projectId does not match {SAFE_ID_RE.pattern}: {project_id}")

        risk_level = data.get("riskLevel", "low")
        if risk_level not in RISK_LEVELS:
            issues.append(f"riskLevel must be one of {RISK_LEVELS}: {risk_level}")

        roles = data.get("roles", [])
        if not roles:
            issues.append("profile.roles is required.")
        for r in roles:
            if not r or not SAFE_ROLE_RE.match(r):
                issues.append(f"role '{r}' does not match {SAFE_ROLE_RE.pattern}")

        phases_data = data.get("phases", [])
        if not phases_data:
            issues.append("profile.phases is required.")
        phases = [PolicyEngine._validate_phase(p, i, issues) for i, p in enumerate(phases_data)]

        return Profile(
            schema_version=data.get("schemaVersion", 1),
            profile_id=profile_id,
            project_id=project_id,
            description=data.get("description", ""),
            risk_level=risk_level,
            roles=roles,
            default_timeout_seconds=data.get("defaultTimeoutSeconds", 300),
            working_directory=data.get("workingDirectory"),
            phases=phases,
        )

    @staticmethod
    def _validate_phase(data: dict, index: int, issues: list[str]) -> Phase:
        path = f"phases[{index}]"
        for k in data:
            if k not in ALLOWED_PHASE_KEYS:
                issues.append(f"Unknown field '{k}' at {path}.")

        phase_id = data.get("id", "")
        if not phase_id or not SAFE_ID_RE.match(phase_id):
            issues.append(f"{path}.id does not match {SAFE_ID_RE.pattern}: {phase_id}")

        risk_level = data.get("riskLevel", "low")
        if risk_level not in RISK_LEVELS:
            issues.append(f"{path}.riskLevel must be one of {RISK_LEVELS}: {risk_level}")

        on_failure = data.get("onFailure", "block")
        if on_failure not in ON_FAILURE_MODES:
            issues.append(f"{path}.onFailure must be one of {ON_FAILURE_MODES}: {on_failure}")

        checks_data = data.get("checks", [])
        checks = [PolicyEngine._validate_check(c, f"{path}.checks[{i}]", issues) for i, c in enumerate(checks_data)]
        finally_data = data.get("finallyChecks", [])
        finally_checks = [PolicyEngine._validate_check(c, f"{path}.finallyChecks[{i}]", issues) for i, c in enumerate(finally_data)]

        return Phase(
            id=phase_id,
            description=data.get("description", ""),
            roles=data.get("roles", []),
            risk_level=risk_level,
            requires_approval=data.get("requiresApproval", False),
            approval_gate=data.get("approvalGate"),
            timeout_seconds=data.get("timeoutSeconds"),
            on_failure=on_failure,
            checks=checks,
            finally_checks=finally_checks,
        )

    @staticmethod
    def _validate_check(data: dict, path: str, issues: list[str]) -> Check:
        for k in data:
            if k not in ALLOWED_CHECK_KEYS:
                issues.append(f"Unknown field '{k}' at {path}.")

        check_id = data.get("id", "")
        if not check_id or not SAFE_ID_RE.match(check_id):
            issues.append(f"{path}.id does not match {SAFE_ID_RE.pattern}: {check_id}")

        risk_level = data.get("riskLevel", "low")
        if risk_level not in RISK_LEVELS:
            issues.append(f"{path}.riskLevel must be one of {RISK_LEVELS}: {risk_level}")

        return Check(
            id=check_id,
            description=data.get("description", ""),
            roles=data.get("roles", []),
            risk_level=risk_level,
            timeout_seconds=data.get("timeoutSeconds"),
            command=data.get("command"),
            required_evidence=data.get("requiredEvidence", []),
            expect_exit_code=data.get("expectExitCode", 0),
            skip=data.get("skip", False),
        )

    @staticmethod
    def select_phases_for_role(profile: Profile, role: str) -> list[Phase]:
        """Select phases applicable to a role."""
        result = []
        for phase in profile.phases:
            if not phase.roles or role in phase.roles:
                result.append(phase)
        return result

    @staticmethod
    def select_checks_for_role(phase: Phase, role: str) -> list[Check]:
        """Select checks applicable to a role within a phase."""
        result = []
        for check in phase.checks:
            if check.skip:
                continue
            if not check.roles or role in check.roles:
                result.append(check)
        return result