"""P1-04: policy gate integration tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.policy.integration import (
    load_profile_for_project,
    evaluate_pre_checks,
    evaluate_task_policy,
    should_block_task,
    should_transition_to_review,
    PolicyEvaluationResult,
)
from bridge.policy.engine import PolicyEngine, Profile, Phase, Check
from bridge.atomic import atomic_write_json


_TRUE_CMD = {"executable": "true", "argv": []}


def _make_profile(phases=None, roles=None):
    return Profile(
        schema_version=1,
        profile_id="test",
        project_id="default",
        roles=roles or ["implement"],
        phases=phases or [_make_phase()],
    )


def _make_check(check_id="c1", roles=None, evidence=None, command=None):
    return Check(
        id=check_id,
        roles=roles or ["implement"],
        required_evidence=evidence or [],
        command=command,
    )


def _make_phase(phase_id="post-check", roles=None, checks=None, on_failure="block", approval=False, gate=None):
    return Phase(
        id=phase_id,
        roles=roles or ["implement"],
        checks=checks or [],
        finally_checks=[],
        on_failure=on_failure,
        requires_approval=approval,
        approval_gate=gate,
    )


class TestEvaluatePreChecks:
    """Test pre-execution check evaluation."""

    def test_no_precheck_phases_passes(self, tmp_path):
        profile = _make_profile(phases=[_make_phase(phase_id="post-check")])
        result = evaluate_pre_checks(profile, tmp_path, tmp_path, "implement")
        assert result.passed is True
        assert result.blocked is False

    def test_precheck_with_evidence_found_passes(self, tmp_path):
        evidence_file = tmp_path / "outbox" / "RESULT.md"
        evidence_file.parent.mkdir(parents=True)
        evidence_file.write_text("test")
        check = _make_check(evidence=["RESULT.md"], command=_TRUE_CMD)
        phase = _make_phase(phase_id="pre-check", checks=[check])
        profile = _make_profile(phases=[phase])
        result = evaluate_pre_checks(profile, tmp_path, tmp_path, "implement")
        assert result.passed is True

    def test_precheck_missing_evidence_blocks(self, tmp_path):
        check = _make_check(evidence=["RESULT.md"], command=_TRUE_CMD)
        phase = _make_phase(phase_id="pre-check", checks=[check], on_failure="block")
        profile = _make_profile(phases=[phase])
        result = evaluate_pre_checks(profile, tmp_path, tmp_path, "implement")
        assert result.blocked is True
        assert result.passed is False

    def test_precheck_missing_evidence_warn_only(self, tmp_path):
        check = _make_check(evidence=["RESULT.md"], command=_TRUE_CMD)
        phase = _make_phase(phase_id="pre-check", checks=[check], on_failure="warn")
        profile = _make_profile(phases=[phase])
        result = evaluate_pre_checks(profile, tmp_path, tmp_path, "implement")
        assert result.blocked is False
        assert len(result.warnings) > 0

    def test_precheck_role_mismatch_skipped(self, tmp_path):
        check = _make_check(evidence=["nonexistent"], roles=["review"], command=_TRUE_CMD)
        phase = _make_phase(phase_id="pre-check", checks=[check], roles=["review"])
        profile = _make_profile(phases=[phase], roles=["implement", "review"])
        result = evaluate_pre_checks(profile, tmp_path, tmp_path, "implement")
        assert result.passed is True

    def test_precheck_no_command_passes(self, tmp_path):
        check = _make_check(evidence=["nonexistent"])
        phase = _make_phase(phase_id="pre-check", checks=[check])
        profile = _make_profile(phases=[phase])
        result = evaluate_pre_checks(profile, tmp_path, tmp_path, "implement")
        assert result.passed is True


class TestEvaluateTaskPolicyExcludesPreCheck:
    """Test that evaluate_task_policy skips pre-check phases."""

    def test_precheck_phase_not_evaluated_in_post(self, tmp_path):
        check = _make_check(evidence=["nonexistent"], command=_TRUE_CMD)
        pre_phase = _make_phase(phase_id="pre-check", checks=[check], on_failure="block")
        post_phase = _make_phase(phase_id="post-check")
        profile = _make_profile(phases=[pre_phase, post_phase])
        result = evaluate_task_policy(profile, tmp_path, tmp_path, "implement")
        assert result.blocked is False
        assert result.passed is True

    def test_postcheck_failure_blocks(self, tmp_path):
        check = _make_check(evidence=["nonexistent"], command=_TRUE_CMD)
        post_phase = _make_phase(phase_id="post-check", checks=[check], on_failure="block")
        profile = _make_profile(phases=[post_phase])
        result = evaluate_task_policy(profile, tmp_path, tmp_path, "implement")
        assert result.blocked is True

    def test_approval_gate_detected(self, tmp_path):
        post_phase = _make_phase(phase_id="post-check", approval=True, gate="manual-review")
        profile = _make_profile(phases=[post_phase])
        result = evaluate_task_policy(profile, tmp_path, tmp_path, "implement")
        assert result.approval_gate is not None


class TestShouldTransition:
    """Test transition decision functions."""

    def test_should_block_when_blocked(self):
        r = PolicyEvaluationResult(passed=False, blocked=True)
        assert should_block_task(r) is True

    def test_should_not_block_when_passed(self):
        r = PolicyEvaluationResult(passed=True, blocked=False)
        assert should_block_task(r) is False

    def test_should_review_when_passed_no_gate(self):
        r = PolicyEvaluationResult(passed=True, blocked=False, approval_gate=None)
        assert should_transition_to_review(r) is True

    def test_should_not_review_when_blocked(self):
        r = PolicyEvaluationResult(passed=True, blocked=True)
        assert should_transition_to_review(r) is False

    def test_should_not_review_when_approval_needed(self):
        r = PolicyEvaluationResult(passed=True, blocked=False, approval_gate="manual")
        assert should_transition_to_review(r) is False


class TestLoadProfile:
    """Test profile loading."""

    def test_no_profile_returns_none(self, tmp_path):
        result = load_profile_for_project(tmp_path, "nonexistent-project")
        assert result is None

    def test_load_valid_profile(self, tmp_path):
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()
        profile_data = {
            "schemaVersion": 1,
            "profileId": "default",
            "projectId": "default",
            "roles": ["implement"],
            "phases": [
                {
                    "id": "post-check",
                    "roles": ["implement"],
                    "checks": [],
                    "finallyChecks": [],
                }
            ],
        }
        (policies_dir / "default.json").write_text(json.dumps(profile_data))
        result = load_profile_for_project(tmp_path, "test-project")
        assert result is not None
        assert result.profile_id == "default"

    def test_load_invalid_profile_returns_none(self, tmp_path):
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()
        (policies_dir / "default.json").write_text("invalid json")
        result = load_profile_for_project(tmp_path, "test-project")
        assert result is None


class TestWorkerPolicyIntegration:
    """Local-First runtime no longer executes Policy Engine gates in worker.py."""

    def test_worker_does_not_import_policy_runtime(self):
        import bridge.worker as w
        assert not hasattr(w, "load_profile_for_project")
        assert not hasattr(w, "evaluate_pre_checks")
        assert not hasattr(w, "evaluate_task_policy")
        assert not hasattr(w, "should_block_task")
        assert not hasattr(w, "should_transition_to_review")


class TestDefaultProfile:
    """Test the shipped default policy profile."""

    def test_default_profile_loads(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        profile = load_profile_for_project(repo_root, "any-project")
        assert profile is not None
        assert profile.profile_id == "default"

    def test_default_profile_has_post_check_phase(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        profile = load_profile_for_project(repo_root, "any-project")
        phase_ids = [p.id for p in profile.phases]
        assert "post-check" in phase_ids
