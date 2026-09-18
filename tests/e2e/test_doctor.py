# AI生成
"""E2E tests for P1-01: production-grade doctor and worker readiness probes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from bridge.doctor import (
    CheckResult, WorkerReadiness,
    check_ssh_connectivity, check_cli_version, check_repo_existence,
    check_repo_clean_state, check_workspace_writable, check_git_available,
    check_worker_host_consistency, check_quota_state, check_model_availability,
    check_codearts_auth, run_doctor, get_ready_workers,
    READY, DEGRADED, AUTH_REQUIRED, QUOTA_EXHAUSTED, OFFLINE,
)


class TestCheckResults:
    """Individual health check functions."""

    def test_check_git_available(self):
        r = check_git_available()
        assert r.name == "git_available"
        assert r.passed is True
        assert r.status == READY

    def test_check_ssh_no_host(self):
        r = check_ssh_connectivity(None)
        assert r.passed is False
        assert r.status == OFFLINE

    def test_check_cli_not_found(self):
        r = check_cli_version(None)
        assert r.passed is False
        assert r.status == DEGRADED

    def test_check_cli_nonexistent_path(self):
        r = check_cli_version("/nonexistent/cli")
        assert r.passed is False
        assert r.status == DEGRADED

    def test_check_repo_no_path(self):
        r = check_repo_existence(None)
        assert r.passed is False
        assert r.status == DEGRADED

    def test_check_repo_exists(self, tmp_path):
        (tmp_path / ".git").mkdir()
        r = check_repo_existence(str(tmp_path))
        assert r.passed is True
        assert r.status == READY

    def test_check_repo_not_git(self, tmp_path):
        r = check_repo_existence(str(tmp_path))
        assert r.passed is False
        assert r.status == DEGRADED

    def test_check_workspace_writable(self, tmp_path):
        r = check_workspace_writable(str(tmp_path / "ws"))
        assert r.passed is True
        assert r.status == READY

    def test_check_workspace_no_path(self):
        r = check_workspace_writable(None)
        assert r.passed is False
        assert r.status == DEGRADED

    def test_check_host_consistency_match(self):
        r = check_worker_host_consistency("192.168.1.1", "192.168.1.1")
        assert r.passed is True
        assert r.status == READY

    def test_check_host_consistency_mismatch(self):
        r = check_worker_host_consistency("192.168.1.1", "192.168.1.2")
        assert r.passed is False
        assert r.status == DEGRADED

    def test_check_host_consistency_local_worker(self):
        r = check_worker_host_consistency(None, "192.168.1.1")
        assert r.passed is True
        assert r.status == READY

    def test_check_quota_no_limit(self):
        r = check_quota_state(None)
        assert r.passed is True
        assert r.status == READY

    def test_check_model_available(self):
        r = check_model_availability("test-model")
        assert r.passed is True
        assert r.status == READY

    def test_check_model_none(self):
        r = check_model_availability(None)
        assert r.passed is False
        assert r.status == DEGRADED

    def test_check_codearts_auth_no_cli(self):
        r = check_codearts_auth(None)
        assert r.passed is False
        assert r.status == AUTH_REQUIRED


class TestRunDoctor:
    """Full doctor check integration."""

    def test_run_doctor_empty(self, tmp_path):
        from bridge.config import WorkerConfig
        result = run_doctor(tmp_path, [], [])
        assert "checks" in result
        assert "workers" in result
        assert len(result["workers"]) == 0

    def test_run_doctor_with_worker(self, tmp_path):
        from bridge.config import WorkerConfig
        w = WorkerConfig(id="w1", transport="local", host=None, model="test-model")
        result = run_doctor(tmp_path, [w], [])
        assert len(result["workers"]) == 1
        assert result["workers"][0]["worker_id"] == "w1"

    def test_get_ready_workers_filters_disabled(self):
        from bridge.config import WorkerConfig
        workers = [
            WorkerConfig(id="w1", transport="local", enabled=True),
            WorkerConfig(id="w2", transport="local", enabled=False),
        ]
        ready = get_ready_workers(workers)
        assert len(ready) == 1
        assert ready[0].id == "w1"

    def test_get_ready_workers_empty(self):
        ready = get_ready_workers([])
        assert ready == []


class TestWorkerReadinessStates:
    """Worker readiness state transitions."""

    def test_ready_state(self):
        wr = WorkerReadiness(worker_id="w1", state=READY)
        assert wr.is_ready is True

    def test_degraded_state(self):
        wr = WorkerReadiness(worker_id="w1", state=DEGRADED)
        assert wr.is_ready is False

    def test_offline_state(self):
        wr = WorkerReadiness(worker_id="w1", state=OFFLINE)
        assert wr.is_ready is False

    def test_auth_required_state(self):
        wr = WorkerReadiness(worker_id="w1", state=AUTH_REQUIRED)
        assert wr.is_ready is False

    def test_quota_exhausted_state(self):
        wr = WorkerReadiness(worker_id="w1", state=QUOTA_EXHAUSTED)
        assert wr.is_ready is False

    def test_all_states_distinct(self):
        states = {READY, DEGRADED, AUTH_REQUIRED, QUOTA_EXHAUSTED, OFFLINE}
        assert len(states) == 5