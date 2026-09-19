# AI生成
"""Tests for Phase 0-8 new modules: core, scheduler, runtime, agents, workspace, application."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ─── Core: IDs ───────────────────────────────────────────────────────────────

class TestIDs:
    def test_assignment_id_format(self):
        from bridge.core.ids import generate_assignment_id
        assert generate_assignment_id().startswith("asg-")

    def test_lease_id_format(self):
        from bridge.core.ids import generate_lease_id
        assert generate_lease_id().startswith("lease-")

    def test_event_id_format(self):
        from bridge.core.ids import generate_event_id
        assert generate_event_id().startswith("evt-")

    def test_session_id_format(self):
        from bridge.core.ids import generate_session_id
        assert generate_session_id("task-1", 1).startswith("sess-task-1-1-")

    def test_ids_unique(self):
        from bridge.core.ids import generate_assignment_id
        ids = {generate_assignment_id() for _ in range(100)}
        assert len(ids) == 100


# ─── Core: Errors ────────────────────────────────────────────────────────────

class TestErrors:
    def test_base_error(self):
        from bridge.core.errors import BridgeError
        assert str(BridgeError("test")) == "test"

    def test_subclass_hierarchy(self):
        from bridge.core.errors import (
            BridgeError, ConfigError, StateTransitionError,
            TaskNotFoundError, WorkerUnavailableError, LeaseExpiredError,
            TimeoutError, PolicyViolationError, IntegrationError,
        )
        for cls in [ConfigError, StateTransitionError, TaskNotFoundError,
                    WorkerUnavailableError, LeaseExpiredError, TimeoutError,
                    PolicyViolationError, IntegrationError]:
            assert issubclass(cls, BridgeError)


# ─── Core: State Machine (v2) ───────────────────────────────────────────────

class TestStateV2:
    def test_v2_states_exist(self):
        from bridge.core.state import (
            CREATED, READY, QUEUED, STARTING, RUNNING,
            VERIFYING, REVIEW_REQUIRED, APPROVED,
            INTEGRATING, INTEGRATED, DONE,
            BLOCKED, FAILED, RETRYABLE, FIX_REQUIRED,
            ASSISTANCE_REQUIRED, STALE, CONFLICT, CANCELLED,
        )
        for s in [CREATED, READY, QUEUED, STARTING, RUNNING,
                  VERIFYING, REVIEW_REQUIRED, APPROVED,
                  INTEGRATING, INTEGRATED, DONE,
                  BLOCKED, FAILED, RETRYABLE, FIX_REQUIRED,
                  ASSISTANCE_REQUIRED, STALE, CONFLICT, CANCELLED]:
            assert isinstance(s, str)

    def test_valid_transition(self):
        from bridge.core.state import is_valid_transition, CREATED, READY
        assert is_valid_transition(CREATED, READY)

    def test_invalid_transition(self):
        from bridge.core.state import is_valid_transition, DONE, RUNNING
        assert not is_valid_transition(DONE, RUNNING)

    def test_set_get_state(self, tmp_path):
        from bridge.core.state import set_state, get_state, CREATED, READY
        task_dir = tmp_path / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        set_state(task_dir, CREATED)
        assert get_state(task_dir)["state"] == CREATED
        set_state(task_dir, READY)
        assert get_state(task_dir)["state"] == READY


# ─── Core: Models ────────────────────────────────────────────────────────────

class TestModels:
    def test_worker_supports_role(self):
        from bridge.core.models import Worker
        w = Worker(id="w1", roles=["implement", "review"])
        assert w.supports_role("implement")
        assert not w.supports_role("test")

    def test_worker_supports_skill(self):
        from bridge.core.models import Worker
        w = Worker(id="w1", skills=["python", "docker"])
        assert w.supports_skill("python")
        assert not w.supports_skill("rust")

    def test_worker_supports_all_skills(self):
        from bridge.core.models import Worker
        w = Worker(id="w1", skills=["python", "docker"])
        assert w.supports_all_skills(["python", "docker"])
        assert not w.supports_all_skills(["python", "rust"])

    def test_worker_supports_workspace(self):
        from bridge.core.models import Worker, WorkspaceConfig
        ws = WorkspaceConfig(supported=["existing", "remote-worktree"])
        w = Worker(id="w1", workspace=ws)
        assert w.supports_workspace("existing")
        assert not w.supports_workspace("local-worktree")

    def test_worker_from_dict_legacy_capabilities(self):
        from bridge.core.models import Worker
        w = Worker.from_dict({"id": "w1", "capabilities": ["implement", "review"]})
        assert w.supports_role("implement")
        assert w.supports_role("review")

    def test_task_from_dict(self):
        from bridge.core.models import Task
        t = Task.from_dict({"taskId": "t1", "projectId": "p1", "role": "implement", "requiredSkills": ["python"]})
        assert t.task_id == "t1"
        assert t.required_skills == ["python"]


# ─── Core: Events ────────────────────────────────────────────────────────────

class TestEvents:
    def test_event_store_append(self, tmp_path):
        from bridge.core.events import EventStore, Event
        store = EventStore(tmp_path / "events")
        store.append(Event(event_id="", type="task.created", task_id="t1", payload={"x": 1}))
        store.append(Event(event_id="", type="task.dispatched", task_id="t1", payload={"y": 2}))
        recent = store.recent(10)
        assert len(recent) == 2
        assert recent[0].type == "task.created"


# ─── Scheduler: Matcher ──────────────────────────────────────────────────────

class TestMatcher:
    def _make_task(self, role="implement", skills=None, preferred=None):
        from bridge.core.models import Task, TaskExecution
        return Task(task_id="t1", project_id="p1", role=role,
                    required_skills=skills or [],
                    execution=TaskExecution(preferred_worker=preferred))

    def test_role_matches(self):
        from bridge.scheduler.matcher import role_matches
        from bridge.core.models import Worker
        w = Worker(id="w1", roles=["implement"])
        assert role_matches(w, "implement")
        assert not role_matches(w, "review")

    def test_skills_match(self):
        from bridge.scheduler.matcher import skills_match
        from bridge.core.models import Worker
        w = Worker(id="w1", skills=["python", "docker"])
        assert skills_match(w, ["python"])
        assert not skills_match(w, ["rust"])

    def test_is_candidate(self):
        from bridge.scheduler.matcher import is_candidate
        from bridge.core.models import Worker
        w = Worker(id="w1", roles=["implement"], skills=["python"])
        assert is_candidate(w, self._make_task(skills=["python"]))

    def test_is_candidate_disabled(self):
        from bridge.scheduler.matcher import is_candidate
        from bridge.core.models import Worker
        w = Worker(id="w1", roles=["implement"], skills=["python"], enabled=False)
        assert not is_candidate(w, self._make_task(skills=["python"]))

    def test_score_worker_preferred(self):
        from bridge.scheduler.matcher import score_worker
        from bridge.core.models import Worker
        w = Worker(id="w1", roles=["implement"], skills=["python"])
        assert score_worker(w, self._make_task(skills=["python"], preferred="w1")) > 1000

    def test_score_worker_skill_overlap(self):
        from bridge.scheduler.matcher import score_worker
        from bridge.core.models import Worker
        w = Worker(id="w1", roles=["implement"], skills=["python", "docker", "rust"])
        assert score_worker(w, self._make_task(skills=["python", "docker"])) >= 20


# ─── Scheduler: Dependency ───────────────────────────────────────────────────

class TestDependency:
    def test_dependency_ready_empty(self, tmp_path):
        from bridge.scheduler.dependency import is_dependency_ready
        assert is_dependency_ready([], tmp_path)

    def test_dependency_ready_external(self, tmp_path):
        from bridge.scheduler.dependency import is_dependency_ready
        assert is_dependency_ready(["nonexistent"], tmp_path)

    def test_dependency_not_ready(self, tmp_path):
        from bridge.scheduler.dependency import is_dependency_ready
        dep_dir = tmp_path / "dep1"
        dep_dir.mkdir()
        (dep_dir / "state.json").write_text('{"state": "RUNNING"}')
        assert not is_dependency_ready(["dep1"], tmp_path)

    def test_dependency_ready_done(self, tmp_path):
        from bridge.scheduler.dependency import is_dependency_ready
        dep_dir = tmp_path / "dep1"
        dep_dir.mkdir()
        (dep_dir / "state.json").write_text('{"state": "DONE"}')
        assert is_dependency_ready(["dep1"], tmp_path)


# ─── Scheduler: Capacity ─────────────────────────────────────────────────────

class TestCapacity:
    def test_has_capacity_empty(self):
        from bridge.scheduler.capacity import has_capacity
        from bridge.core.models import Worker
        assert has_capacity(Worker(id="w1", concurrency_limit=2), [])

    def test_has_capacity_full(self):
        from bridge.scheduler.capacity import has_capacity
        from bridge.core.models import Worker, Assignment
        w = Worker(id="w1", concurrency_limit=1)
        a = Assignment(assignment_id="a1", task_id="t1", worker_id="w1", role="implement")
        assert not has_capacity(w, [a])

    def test_filter_with_capacity(self):
        from bridge.scheduler.capacity import filter_with_capacity
        from bridge.core.models import Worker, Assignment
        w1 = Worker(id="w1", concurrency_limit=1)
        w2 = Worker(id="w2", concurrency_limit=2)
        a = Assignment(assignment_id="a1", task_id="t1", worker_id="w1", role="implement")
        result = filter_with_capacity([w1, w2], [a])
        assert w2 in result and w1 not in result


# ─── Scheduler: Affinity ─────────────────────────────────────────────────────

class TestAffinity:
    def test_excluded_workers(self):
        from bridge.scheduler.affinity import get_excluded_workers
        from bridge.core.models import Task, TaskExecution
        t = Task(task_id="t1", project_id="p1", execution=TaskExecution(excluded_workers=["w1", "w3"]))
        excluded = get_excluded_workers(t, [])
        assert "w1" in excluded and "w3" in excluded

    def test_review_anti_affinity(self):
        from bridge.scheduler.affinity import get_excluded_workers
        from bridge.core.models import Task, TaskExecution, TaskReview, Assignment
        t = Task(task_id="t1", project_id="p1", role="review",
                 execution=TaskExecution(), review=TaskReview(independent_worker=True))
        a = Assignment(assignment_id="a1", task_id="t1", worker_id="impl-w1", role="implement")
        assert "impl-w1" in get_excluded_workers(t, [a])


# ─── Scheduler: Lease ────────────────────────────────────────────────────────

class TestLease:
    def test_create_and_get_lease(self, tmp_path):
        from bridge.scheduler.lease import create_lease, get_active_lease
        lease = create_lease(tmp_path, "task-1", "worker-1", ttl_minutes=30)
        assert lease.task_id == "task-1"
        active = get_active_lease(tmp_path, "task-1")
        assert active is not None

    def test_release_lease(self, tmp_path):
        from bridge.scheduler.lease import create_lease, release_lease, get_active_lease
        lease = create_lease(tmp_path, "task-1", "worker-1", ttl_minutes=30)
        release_lease(tmp_path, lease.lease_id)
        assert get_active_lease(tmp_path, "task-1") is None


# ─── Runtime: Heartbeat ──────────────────────────────────────────────────────

class TestHeartbeat:
    def test_write_and_read(self, tmp_path):
        from bridge.runtime.heartbeat import write_heartbeat, read_heartbeat, HeartbeatInfo
        write_heartbeat(tmp_path, HeartbeatInfo(task_id="t1", worker_id="w1"))
        read = read_heartbeat(tmp_path, "t1")
        assert read is not None and read.task_id == "t1"

    def test_is_stale_no_heartbeat(self, tmp_path):
        from bridge.runtime.heartbeat import is_stale
        assert is_stale(tmp_path, "nonexistent", 5)

    def test_remove_heartbeat(self, tmp_path):
        from bridge.runtime.heartbeat import write_heartbeat, read_heartbeat, remove_heartbeat, HeartbeatInfo
        write_heartbeat(tmp_path, HeartbeatInfo(task_id="t1", worker_id="w1"))
        remove_heartbeat(tmp_path, "t1")
        assert read_heartbeat(tmp_path, "t1") is None


# ─── Runtime: Cancellation ───────────────────────────────────────────────────

class TestCancellation:
    def test_request_and_check(self, tmp_path):
        from bridge.runtime.cancellation import request_cancellation, is_cancelled
        assert not is_cancelled(tmp_path, "t1")
        request_cancellation(tmp_path, "t1", "test")
        assert is_cancelled(tmp_path, "t1")

    def test_complete_cancellation(self, tmp_path):
        from bridge.runtime.cancellation import request_cancellation, complete_cancellation, get_cancellation
        request_cancellation(tmp_path, "t1")
        complete_cancellation(tmp_path, "t1", exit_code=0)
        assert get_cancellation(tmp_path, "t1")["status"] == "completed"

    def test_pending_cancellations(self, tmp_path):
        from bridge.runtime.cancellation import request_cancellation, get_pending_cancellations
        request_cancellation(tmp_path, "t1")
        request_cancellation(tmp_path, "t2")
        pending = get_pending_cancellations(tmp_path)
        assert "t1" in pending and "t2" in pending


# ─── Runtime: Timeout ────────────────────────────────────────────────────────

class TestTimeout:
    def test_no_timeout(self):
        from bridge.runtime.timeout import TimeoutConfig, check_timeout
        from datetime import datetime, timezone
        status = check_timeout(datetime.now(timezone.utc), TimeoutConfig())
        assert not status.soft_exceeded and not status.hard_exceeded

    def test_hard_timeout_exceeded(self):
        from bridge.runtime.timeout import TimeoutConfig, check_timeout
        from datetime import datetime, timedelta, timezone
        start = datetime.now(timezone.utc) - timedelta(seconds=2)
        assert check_timeout(start, TimeoutConfig(hard_timeout_minutes=0.01)).hard_exceeded

    def test_from_task_meta(self):
        from bridge.runtime.timeout import from_task_meta
        config = from_task_meta({"execution": {"softTimeoutMinutes": 10, "hardTimeoutMinutes": 30, "targetMinutes": 15}})
        assert config.soft_timeout_minutes == 10 and config.hard_timeout_minutes == 30

    def test_from_task_meta_v1_compat(self):
        from bridge.runtime.timeout import from_task_meta
        assert from_task_meta({"timeoutMinutes": 60}).hard_timeout_minutes == 60


# ─── Runtime: Session ────────────────────────────────────────────────────────

class TestSession:
    def test_create_session(self, tmp_path):
        from bridge.runtime.session import create_session, load_session
        session = create_session(tmp_path, "t1", "w1", "asg-1")
        assert session.task_id == "t1" and session.status == "active"
        loaded = load_session(tmp_path, session.session_id)
        assert loaded is not None and loaded.task_id == "t1"

    def test_end_session(self, tmp_path):
        from bridge.runtime.session import create_session, end_session, load_session
        session = create_session(tmp_path, "t1", "w1", "asg-1")
        end_session(tmp_path, session.session_id, "completed", exit_code=0)
        assert load_session(tmp_path, session.session_id).status == "completed"

    def test_find_active_session(self, tmp_path):
        from bridge.runtime.session import create_session, find_active_session
        create_session(tmp_path, "t1", "w1", "asg-1")
        assert find_active_session(tmp_path, "t1") is not None


# ─── Runtime: Recovery ───────────────────────────────────────────────────────

class TestRecovery:
    def test_find_stale_no_sessions(self, tmp_path):
        from bridge.runtime.recovery import find_stale_sessions
        assert find_stale_sessions(tmp_path) == []

    def test_recover_no_sessions(self, tmp_path):
        from bridge.runtime.recovery import recover_stale_sessions
        assert recover_stale_sessions(tmp_path) == []


# ─── Agents ──────────────────────────────────────────────────────────────────

class TestAgentRegistry:
    def test_codearts_registered(self):
        from bridge.agents.registry import is_registered
        assert is_registered("codearts")

    def test_get_adapter(self):
        from bridge.agents.registry import get_adapter
        from bridge.agents.codearts import CodeArtsAdapter
        assert isinstance(get_adapter("codearts"), CodeArtsAdapter)

    def test_unknown_type(self):
        from bridge.agents.registry import get_adapter
        with pytest.raises(KeyError):
            get_adapter("unknown")

    def test_list_types(self):
        from bridge.agents.registry import list_types
        assert "codearts" in list_types()


class TestCodeArtsAdapter:
    def test_agent_type(self):
        from bridge.agents.codearts import CodeArtsAdapter
        assert CodeArtsAdapter().agent_type == "codearts"

    def test_parse_output(self):
        from bridge.agents.codearts import CodeArtsAdapter
        result = CodeArtsAdapter().parse_output('{"sessionID": "s1", "timestamp": "2024-01-01"}')
        assert result["sessionId"] == "s1"


# ─── Workspace ───────────────────────────────────────────────────────────────

class TestWorkspaceFactory:
    def test_create_existing(self):
        from bridge.workspace import create_workspace_manager, ExistingWorkspace
        assert isinstance(create_workspace_manager("existing"), ExistingWorkspace)

    def test_create_remote_worktree(self):
        from bridge.workspace import create_workspace_manager, RemoteWorktreeWorkspace
        assert isinstance(create_workspace_manager("remote-worktree"), RemoteWorktreeWorkspace)

    def test_create_unknown(self):
        from bridge.workspace import create_workspace_manager
        with pytest.raises(ValueError):
            create_workspace_manager("unknown")


class TestExistingWorkspace:
    def test_prepare(self):
        from bridge.workspace import ExistingWorkspace
        from types import SimpleNamespace
        mgr = ExistingWorkspace()
        project = SimpleNamespace(project_root="/home/user/project")
        result = mgr.prepare(project, "task-1", Path("/tmp/task-1"))
        assert result.workspace_path == "/home/user/project" and not result.is_remote


# ─── Application: Task Service ───────────────────────────────────────────────

class TestTaskService:
    def test_create_task(self, tmp_path):
        from bridge.application.task_service import create_task, get_task_status
        task_file = tmp_path / "task.md"
        task_file.write_text("# Test task\n", encoding="utf-8")
        meta = create_task(bridge_root=tmp_path, project_id="p1", worker_id="w1",
                           role="implement", task_id="t1", task_file=str(task_file),
                           required_skills=["python"])
        assert meta["taskId"] == "t1" and meta["schemaVersion"] == 2
        status = get_task_status(tmp_path, "t1")
        assert status["state"] == "READY"

    def test_cancel_task(self, tmp_path):
        from bridge.application.task_service import create_task, cancel_task
        task_file = tmp_path / "task.md"
        task_file.write_text("# Test\n", encoding="utf-8")
        create_task(bridge_root=tmp_path, project_id="p1", worker_id="w1",
                    role="implement", task_id="t1", task_file=str(task_file))
        assert cancel_task(tmp_path, "t1", "test")["state"] == "CANCELLED"

    def test_list_tasks(self, tmp_path):
        from bridge.application.task_service import create_task, list_tasks
        for i in range(3):
            f = tmp_path / f"task{i}.md"
            f.write_text(f"# Task {i}\n", encoding="utf-8")
            create_task(bridge_root=tmp_path, project_id="p1", worker_id="w1",
                        role="implement", task_id=f"t{i}", task_file=str(f))
        assert len(list_tasks(tmp_path)) == 3


# ─── Application: Review Service ─────────────────────────────────────────────

class TestReviewService:
    def _setup_review_task(self, tmp_path):
        from bridge.core.state import set_state, CREATED
        task_dir = tmp_path / "tasks" / "t1"
        (task_dir / "inbox").mkdir(parents=True)
        (task_dir / "outbox").mkdir(parents=True)
        set_state(task_dir, CREATED)
        for s in ["READY", "QUEUED", "STARTING", "RUNNING", "VERIFYING", "REVIEW_REQUIRED"]:
            set_state(task_dir, s)

    def test_review_pass(self, tmp_path):
        from bridge.application.review_service import review_pass
        self._setup_review_task(tmp_path)
        result = review_pass(tmp_path, "t1", reviewer_id="w2")
        assert result.success and result.new_state == "APPROVED"

    def test_review_fix(self, tmp_path):
        from bridge.application.review_service import review_fix
        self._setup_review_task(tmp_path)
        fix_file = tmp_path / "fix.md"
        fix_file.write_text("# Fix needed\n", encoding="utf-8")
        result = review_fix(tmp_path, "t1", str(fix_file), reviewer_id="w2")
        assert result.success and result.new_state == "FIX_REQUIRED"

    def test_review_independence(self):
        from bridge.application.review_service import check_review_independence
        assert check_review_independence("w1", "w2")
        assert not check_review_independence("w1", "w1")



# ─── Policy: Integration ─────────────────────────────────────────────────────

class TestPolicyIntegration:
    def test_should_transition_to_review(self):
        from bridge.policy.integration import should_transition_to_review, PolicyEvaluationResult
        assert should_transition_to_review(PolicyEvaluationResult(passed=True, blocked=False, approval_gate=None))

    def test_should_not_transition_when_blocked(self):
        from bridge.policy.integration import should_transition_to_review, PolicyEvaluationResult
        assert not should_transition_to_review(PolicyEvaluationResult(passed=True, blocked=True))

    def test_should_not_transition_when_approval_needed(self):
        from bridge.policy.integration import should_transition_to_review, PolicyEvaluationResult
        assert not should_transition_to_review(PolicyEvaluationResult(passed=True, approval_gate="gate-1"))

    def test_should_block_task(self):
        from bridge.policy.integration import should_block_task, PolicyEvaluationResult
        assert should_block_task(PolicyEvaluationResult(passed=False, blocked=True))
        assert not should_block_task(PolicyEvaluationResult(passed=True, blocked=False))


# ─── Integration Module ──────────────────────────────────────────────────────

class TestIntegrationModule:
    def test_get_conflict_files_no_conflicts(self, tmp_path):
        from bridge.integration import get_conflict_files
        assert get_conflict_files(tmp_path) == []

    def test_verify_integration_custom_command(self, tmp_path):
        from bridge.integration import verify_integration
        assert verify_integration(tmp_path, ["echo", "hello"])


# ─── Import Smoke Tests ──────────────────────────────────────────────────────

class TestImports:
    def test_import_core(self):
        from bridge.core import ids, errors, state, models, events

    def test_import_scheduler(self):
        from bridge.scheduler import matcher, dependency, capacity, affinity, lease, planner

    def test_import_runtime(self):
        from bridge.runtime import process, heartbeat, cancellation, timeout, session, recovery, supervisor

    def test_import_agents(self):
        from bridge.agents import base, codearts, registry

    def test_import_workspace(self):
        from bridge.workspace import base, existing, local_worktree, remote_worktree

    def test_import_application(self):
        from bridge.application import task_service, dispatch_service, review_service, integration_service

    def test_import_policy_integration(self):
        from bridge.policy import integration

    def test_import_integration(self):
        import bridge.integration
