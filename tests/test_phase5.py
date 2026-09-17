# AI生成
"""Tests for Phase 5: policy engine, runtime, timeout."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bridge.policy.engine import PolicyEngine, Profile, Phase, Check
from bridge.policy.runtime import evaluate_check, evaluate_phase, find_unmet_approval, CheckResult
from bridge.policy.timeout import TimeoutPolicy


class TestPolicyEngine:
    def _make_profile_data(self):
        return {
            "schemaVersion": 1,
            "profileId": "test-profile",
            "projectId": "test-project",
            "description": "Test profile",
            "riskLevel": "low",
            "roles": ["implement", "review"],
            "defaultTimeoutSeconds": 300,
            "phases": [
                {
                    "id": "build",
                    "description": "Build phase",
                    "roles": ["implement"],
                    "riskLevel": "low",
                    "requiresApproval": False,
                    "onFailure": "block",
                    "checks": [
                        {
                            "id": "unit-tests",
                            "description": "Run unit tests",
                            "roles": ["implement"],
                            "riskLevel": "low",
                            "command": {"executable": "echo", "argv": ["ok"]},
                            "expectExitCode": 0,
                        }
                    ],
                },
                {
                    "id": "deploy",
                    "description": "Deploy phase",
                    "roles": ["implement"],
                    "riskLevel": "high",
                    "requiresApproval": True,
                    "approvalGate": "deploy-approval",
                    "onFailure": "block",
                    "checks": [],
                },
            ],
        }

    def test_load_profile(self, tmp_path):
        data = self._make_profile_data()
        p = tmp_path / "profile.json"
        p.write_text(json.dumps(data))
        profile = PolicyEngine.load_profile(p)
        assert profile.profile_id == "test-profile"
        assert profile.project_id == "test-project"
        assert len(profile.phases) == 2
        assert profile.phases[0].id == "build"
        assert profile.phases[1].id == "deploy"

    def test_invalid_profile_id(self, tmp_path):
        data = self._make_profile_data()
        data["profileId"] = "Invalid ID"
        p = tmp_path / "profile.json"
        p.write_text(json.dumps(data))
        try:
            PolicyEngine.load_profile(p)
            assert False
        except ValueError as e:
            assert "profileId" in str(e)

    def test_unknown_field(self, tmp_path):
        data = self._make_profile_data()
        data["unknownField"] = "value"
        p = tmp_path / "profile.json"
        p.write_text(json.dumps(data))
        try:
            PolicyEngine.load_profile(p)
            assert False
        except ValueError as e:
            assert "Unknown field" in str(e)

    def test_select_phases_for_role(self, tmp_path):
        data = self._make_profile_data()
        p = tmp_path / "profile.json"
        p.write_text(json.dumps(data))
        profile = PolicyEngine.load_profile(p)
        phases = PolicyEngine.select_phases_for_role(profile, "implement")
        assert len(phases) == 2
        phases = PolicyEngine.select_phases_for_role(profile, "review")
        assert len(phases) == 0  # phases restricted to implement role

    def test_select_checks_for_role(self, tmp_path):
        data = self._make_profile_data()
        p = tmp_path / "profile.json"
        p.write_text(json.dumps(data))
        profile = PolicyEngine.load_profile(p)
        phase = profile.phases[0]
        checks = PolicyEngine.select_checks_for_role(phase, "implement")
        assert len(checks) == 1
        assert checks[0].id == "unit-tests"
        checks = PolicyEngine.select_checks_for_role(phase, "review")
        assert len(checks) == 0  # check restricted to implement


class TestPolicyRuntime:
    def test_evaluate_check_skip(self, tmp_path):
        check = Check(id="skip-check", skip=True)
        result = evaluate_check(check, tmp_path, tmp_path)
        assert result.passed
        assert "skipped" in result.message

    def test_evaluate_check_no_command(self, tmp_path):
        check = Check(id="no-cmd")
        result = evaluate_check(check, tmp_path, tmp_path)
        assert result.passed

    def test_evaluate_check_pass(self, tmp_path):
        check = Check(
            id="echo-test",
            command={"executable": "echo", "argv": ["hello"]},
            expect_exit_code=0,
        )
        result = evaluate_check(check, tmp_path, tmp_path)
        assert result.passed
        assert result.exit_code == 0

    def test_evaluate_check_wrong_exit(self, tmp_path):
        check = Check(
            id="false-test",
            command={"executable": "python", "argv": ["-c", "import sys; sys.exit(1)"]},
            expect_exit_code=0,
        )
        result = evaluate_check(check, tmp_path, tmp_path)
        assert not result.passed

    def test_evaluate_check_evidence(self, tmp_path):
        # Create evidence file
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "RESULT.md").write_text("result")
        check = Check(
            id="evidence-check",
            command={"executable": "echo", "argv": ["ok"]},
            required_evidence=["RESULT.md"],
        )
        result = evaluate_check(check, tmp_path, tmp_path)
        assert result.passed
        assert result.evidence_found["RESULT.md"] is True

    def test_evaluate_check_missing_evidence(self, tmp_path):
        check = Check(
            id="missing-evidence",
            command={"executable": "echo", "argv": ["ok"]},
            required_evidence=["RESULT.md"],
        )
        result = evaluate_check(check, tmp_path, tmp_path)
        assert not result.passed
        assert "missing evidence" in result.message

    def test_find_unmet_approval(self, tmp_path):
        data = {
            "schemaVersion": 1,
            "profileId": "test",
            "projectId": "proj",
            "roles": ["implement"],
            "phases": [
                {
                    "id": "deploy",
                    "roles": ["implement"],
                    "requiresApproval": True,
                    "approvalGate": "deploy-gate",
                    "checks": [],
                },
            ],
        }
        p = tmp_path / "profile.json"
        p.write_text(json.dumps(data))
        profile = PolicyEngine.load_profile(p)

        from bridge.policy.runtime import PhaseResult
        phase_results = [PhaseResult(phase_id="deploy", passed=True, approval_required=True)]
        gate = find_unmet_approval(profile, phase_results)
        assert gate == "deploy-gate"


class TestTimeoutPolicy:
    def test_defaults(self):
        tp = TimeoutPolicy()
        assert tp.target_seconds == 600
        assert tp.soft_seconds == 720
        assert tp.hard_seconds == 900

    def test_from_minutes(self):
        tp = TimeoutPolicy.from_minutes(10, 12, 15)
        assert tp.target_seconds == 600
        assert tp.soft_seconds == 720
        assert tp.hard_seconds == 900

    def test_validation(self):
        try:
            TimeoutPolicy(target_seconds=0)
            assert False
        except ValueError:
            pass
        try:
            TimeoutPolicy(target_seconds=100, soft_seconds=50)
            assert False
        except ValueError:
            pass

    def test_is_soft_timeout(self):
        tp = TimeoutPolicy(target_seconds=60, soft_seconds=120, hard_seconds=180)
        assert not tp.is_soft_timeout(60)
        assert tp.is_soft_timeout(120)
        assert tp.is_soft_timeout(150)

    def test_is_hard_timeout(self):
        tp = TimeoutPolicy(target_seconds=60, soft_seconds=120, hard_seconds=180)
        assert not tp.is_hard_timeout(120)
        assert tp.is_hard_timeout(180)
        assert tp.is_hard_timeout(200)

    def test_remaining(self):
        tp = TimeoutPolicy(target_seconds=60, soft_seconds=120, hard_seconds=180)
        assert tp.remaining_to_hard(100) == 80
        assert tp.remaining_to_soft(100) == 20
        assert tp.remaining_to_hard(200) == 0