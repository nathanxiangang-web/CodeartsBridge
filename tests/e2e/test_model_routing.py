"""P1-03: model routing and role-based model resolution tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.codearts import (
    REQUIRED_MODEL,
    ROLE_MODEL_MAP,
    resolve_model,
    new_worker_run_arguments,
)
from bridge.config import ProjectConfig, WorkerConfig, VALID_ROLES


class TestResolveModel:
    """Test resolve_model priority and fallback logic."""

    def test_architect_role_in_valid_roles(self):
        assert "architect" in VALID_ROLES

    def test_role_model_map_has_all_roles(self):
        for role in ("architect", "implement", "review", "test"):
            assert role in ROLE_MODEL_MAP

    def test_worker_model_override_takes_priority(self):
        w = WorkerConfig(id="w1", transport="ssh", model="custom/worker-model")
        p = ProjectConfig(id="p1", transport="local", project_root="/tmp", model="custom/project-model")
        assert resolve_model(role="implement", worker=w, project=p) == "custom/worker-model"

    def test_project_model_used_when_worker_is_default(self):
        w = WorkerConfig(id="w1", transport="ssh", model=REQUIRED_MODEL)
        p = ProjectConfig(id="p1", transport="local", project_root="/tmp", model="custom/project-model")
        assert resolve_model(role="implement", worker=w, project=p) == "custom/project-model"

    def test_role_mapping_used_when_both_default(self):
        w = WorkerConfig(id="w1", transport="ssh", model=REQUIRED_MODEL)
        p = ProjectConfig(id="p1", transport="local", project_root="/tmp", model=REQUIRED_MODEL)
        result = resolve_model(role="review", worker=w, project=p)
        assert result == ROLE_MODEL_MAP["review"]

    def test_default_sentinel_triggers_role_mapping(self):
        w = WorkerConfig(id="w1", transport="ssh", model="default")
        p = ProjectConfig(id="p1", transport="local", project_root="/tmp", model="default")
        result = resolve_model(role="test", worker=w, project=p)
        assert result == ROLE_MODEL_MAP["test"]

    def test_empty_string_sentinel_triggers_role_mapping(self):
        w = WorkerConfig(id="w1", transport="ssh", model="")
        p = ProjectConfig(id="p1", transport="local", project_root="/tmp", model="")
        result = resolve_model(role="implement", worker=w, project=p)
        assert result == ROLE_MODEL_MAP["implement"]

    def test_fallback_when_no_role(self):
        assert resolve_model(role=None) == REQUIRED_MODEL

    def test_fallback_for_unknown_role(self):
        assert resolve_model(role="unknown-role") == REQUIRED_MODEL

    def test_no_worker_no_project(self):
        result = resolve_model(role="architect")
        assert result == ROLE_MODEL_MAP["architect"]

    def test_worker_none_project_with_custom_model(self):
        p = ProjectConfig(id="p1", transport="local", project_root="/tmp", model="custom/project")
        assert resolve_model(role="implement", worker=None, project=p) == "custom/project"

    def test_worker_with_custom_model_project_none(self):
        w = WorkerConfig(id="w1", transport="ssh", model="custom/worker")
        assert resolve_model(role="implement", worker=w, project=None) == "custom/worker"


class TestTransportModelParameter:
    """Test that transports accept and use the model parameter."""

    def test_local_transport_accepts_model_param(self):
        from bridge.transport.local import LocalTransport
        import inspect
        sig = inspect.signature(LocalTransport.run)
        assert "model" in sig.parameters

    def test_ssh_transport_accepts_model_param(self):
        from bridge.transport.ssh import SshTransport
        import inspect
        sig = inspect.signature(SshTransport.run)
        assert "model" in sig.parameters

    def test_ssh_shell_transport_accepts_model_param(self):
        from bridge.transport.ssh_shell import SshShellTransport
        import inspect
        sig = inspect.signature(SshShellTransport.run)
        assert "model" in sig.parameters

    def test_remote_worktree_transport_accepts_model_param(self):
        from bridge.transport.remote_worktree import RemoteWorktreeTransport
        import inspect
        sig = inspect.signature(RemoteWorktreeTransport.run)
        assert "model" in sig.parameters

    def test_base_transport_accepts_model_param(self):
        from bridge.transport.base import TransportBase
        import inspect
        sig = inspect.signature(TransportBase.run)
        assert "model" in sig.parameters


class TestNewWorkerRunArgumentsWithModel:
    """Test that new_worker_run_arguments correctly passes model to CLI."""

    def test_custom_model_passed_to_args(self):
        args = new_worker_run_arguments(
            prompt="test prompt",
            model="custom/model",
            task_id="test-task",
        )
        assert "-m" in args
        idx = args.index("-m")
        assert args[idx + 1] == "custom/model"

    def test_none_model_omits_m_flag(self):
        args = new_worker_run_arguments(
            prompt="test prompt",
            model=None,
            task_id="test-task",
        )
        assert "-m" not in args

    def test_required_model_passed_to_args(self):
        args = new_worker_run_arguments(
            prompt="test prompt",
            model=REQUIRED_MODEL,
            task_id="test-task",
        )
        assert "-m" in args
        idx = args.index("-m")
        assert args[idx + 1] == REQUIRED_MODEL