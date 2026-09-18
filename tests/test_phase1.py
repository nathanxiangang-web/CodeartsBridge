# AI生成
"""Tests for Phase 1: atomic, locks, config, state."""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add src to path for testing without install
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bridge.atomic import atomic_write_text, atomic_write_json, read_json, read_json_or_none
from bridge.state import (
    set_state, get_state, READY, QUEUED, RUNNING, REVIEW_REQUIRED, DONE,
    is_candidate, is_active, is_terminal, CANDIDATE_STATES, ACTIVE_STATES,
)
from bridge.config import (
    assert_safe_id, assert_safe_session_id,
    load_registry, load_workers_registry, get_project, get_worker,
    ProjectConfig, WorkerConfig,
)


class TestAtomic:
    def test_write_text(self, tmp_path):
        p = tmp_path / "f.txt"
        atomic_write_text(p, "hello")
        assert p.read_text(encoding="utf-8") == "hello"

    def test_write_json(self, tmp_path):
        p = tmp_path / "f.json"
        atomic_write_json(p, {"a": 1, "b": [2, 3]})
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["a"] == 1
        assert data["b"] == [2, 3]

    def test_read_json(self, tmp_path):
        p = tmp_path / "f.json"
        atomic_write_json(p, {"x": 42})
        assert read_json(p)["x"] == 42

    def test_read_json_missing(self, tmp_path):
        try:
            read_json(tmp_path / "nope.json")
            assert False, "should raise"
        except FileNotFoundError:
            pass

    def test_read_json_or_none(self, tmp_path):
        assert read_json_or_none(tmp_path / "nope.json") is None
        p = tmp_path / "f.json"
        atomic_write_json(p, {"x": 1})
        assert read_json_or_none(p)["x"] == 1

    def test_overwrite(self, tmp_path):
        p = tmp_path / "f.txt"
        atomic_write_text(p, "first")
        atomic_write_text(p, "second")
        assert p.read_text() == "second"


class TestState:
    def test_initial_state(self, tmp_path):
        s = set_state(tmp_path, READY, message="created")
        assert s["status"] == READY
        assert s["schemaVersion"] == 1
        assert s["taskId"] == tmp_path.name
        assert s["attempt"] == 0
        assert s["message"] == "created"
        assert s["processId"] is None
        assert s["exitCode"] is None

    def test_merge_preserves_fields(self, tmp_path):
        set_state(tmp_path, READY, message="init")
        set_state(tmp_path, QUEUED, message="queued")
        s = get_state(tmp_path)
        assert s["status"] == QUEUED
        assert s["message"] == "queued"
        assert s["taskId"] == tmp_path.name

    def test_preserves_session_and_telemetry(self, tmp_path):
        set_state(tmp_path, RUNNING, session_id="abc-123", session_mode="new",
                   heartbeat_events=5, heartbeat_think=2, heartbeat_tool=3)
        set_state(tmp_path, REVIEW_REQUIRED, message="done")
        s = get_state(tmp_path)
        assert s["sessionId"] == "abc-123"
        assert s["sessionMode"] == "new"
        assert s["heartbeatEvents"] == 5
        assert s["heartbeatThink"] == 2
        assert s["heartbeatTool"] == 3

    def test_attempt_preserved(self, tmp_path):
        set_state(tmp_path, READY)
        # Simulate old state with attempt=2
        st = get_state(tmp_path)
        st["attempt"] = 2
        from bridge.atomic import atomic_write_json
        atomic_write_json(tmp_path / "state.json", st)
        set_state(tmp_path, RUNNING)
        s = get_state(tmp_path)
        assert s["attempt"] == 2

    def test_candidate_states(self):
        assert is_candidate(READY)
        assert is_candidate("FIX_REQUIRED")
        assert is_candidate("RETRYABLE")
        assert not is_candidate(RUNNING)
        assert not is_candidate(DONE)

    def test_active_states(self):
        assert is_active(QUEUED)
        assert is_active(STARTING := "STARTING")
        assert is_active(RUNNING)
        assert not is_active(READY)
        assert not is_active(DONE)

    def test_terminal_states(self):
        assert is_terminal(DONE)
        assert is_terminal("FAILED")
        assert is_terminal("BLOCKED")
        assert not is_terminal(RUNNING)


class TestConfig:
    def test_safe_id(self):
        assert_safe_id("task-001")
        assert_safe_id("cloudsite.rc1.w01")
        try:
            assert_safe_id("task 001")
            assert False
        except ValueError:
            pass

    def test_safe_session_id(self):
        assert_safe_session_id("abc-123_xyz")
        try:
            assert_safe_session_id("abc.123")
            assert False
        except ValueError:
            pass

    def test_load_registry(self):
        root = Path(__file__).parent.parent
        reg = load_registry(root / "projects.json")
        assert reg.schema_version == 1
        assert len(reg.projects) > 0
        # Check a known project
        p = get_project(reg, "bridge-selftest")
        assert p.transport == "local"
        assert p.model == "huaweicloud-maas/GLM-5.2"

    def test_load_workers(self):
        root = Path(__file__).parent.parent
        wr = load_workers_registry(root / "workers.json")
        assert wr.schema_version == 1
        assert len(wr.workers) == 4
        w = get_worker(wr, "bus-w04-qa")
        assert "implement" not in w.capabilities
        assert "review" in w.capabilities

    def test_project_registry_defaults_are_inherited_and_overridable(self, tmp_path):
        pf = tmp_path / "projects.json"
        atomic_write_json(pf, {
            "schemaVersion": 1,
            "defaults": {
                "transport": "ssh",
                "runMode": "sandbox",
                "model": "default-model",
                "timeoutMinutes": 77,
                "sshHost": "default@example",
            },
            "projects": [
                {"id": "inherits", "projectRoot": "/srv/inherits"},
                {
                    "id": "override",
                    "projectRoot": "/srv/override",
                    "transport": "local",
                    "model": "override-model",
                },
            ],
        })

        reg = load_registry(pf)
        inherited = get_project(reg, "inherits")
        overridden = get_project(reg, "override")

        assert inherited.transport == "ssh"
        assert inherited.run_mode == "sandbox"
        assert inherited.model == "default-model"
        assert inherited.timeout_minutes == 77
        assert inherited.ssh_host == "default@example"

        assert overridden.transport == "local"
        assert overridden.model == "override-model"
        assert overridden.timeout_minutes == 77

    def test_worker_registry_defaults_are_inherited_and_overridable(self, tmp_path):
        wf = tmp_path / "workers.json"
        atomic_write_json(wf, {
            "schemaVersion": 1,
            "defaults": {
                "transport": "ssh",
                "model": "default-worker-model",
                "concurrencyLimit": 3,
                "enabled": False,
                "capabilities": ["implement"],
            },
            "workers": [
                {"id": "inherits"},
                {
                    "id": "override",
                    "enabled": True,
                    "capabilities": ["review", "test"],
                },
            ],
        })

        reg = load_workers_registry(wf)
        inherited = get_worker(reg, "inherits")
        overridden = get_worker(reg, "override")

        assert inherited.transport == "ssh"
        assert inherited.model == "default-worker-model"
        assert inherited.concurrency_limit == 3
        assert inherited.enabled is False
        assert inherited.capabilities == ["implement"]

        assert overridden.enabled is True
        assert overridden.concurrency_limit == 3
        assert overridden.capabilities == ["review", "test"]

    def test_project_not_found(self):
        root = Path(__file__).parent.parent
        reg = load_registry(root / "projects.json")
        try:
            get_project(reg, "nonexistent")
            assert False
        except ValueError:
            pass