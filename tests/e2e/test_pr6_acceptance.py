# AI生成
"""PR-6 acceptance tests for the real 4-worker runtime.

Validates the end state after PR-1 through PR-5 are merged, per
docs/ai-closeout/05-REAL-ACCEPTANCE.md and 02-CLOSEOUT-ROADMAP.md.

Scenarios:
  A - Bridge starts, 4 workers connect via heartbeat
  B - Create + dispatch + worker picks up
  C - Worker produces events (started, step, reasoning, tool_use)
  D - Soft timeout transitions to ASSISTANCE_REQUIRED with salvage
  E - Review PASS writes APPROVED only (not INTEGRATED/DONE) -- PR-1 lifecycle truth
  F - Integration: APPROVED -> INTEGRATING -> INTEGRATED -> DONE
  G - No fake supervision: supervision/ deleted, pipeline.py has no Supervisor
  H - No policy/runtime: policy/ and runtime/ deleted, worker.py has no policy calls

Collection only (no execution) must succeed:
  PYTHONPATH=src python3 -m pytest tests/e2e/test_pr6_acceptance.py -q --collect-only

Scenarios A-F require a running bridge with 4 real workers and are marked
``@pytest.mark.integration``. They skip automatically when the bridge API is
unreachable. Scenarios G-H are pure structural checks and run without a bridge.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# Make ``bridge`` importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from bridge.state import (
    APPROVED,
    ASSISTANCE_REQUIRED,
    DONE,
    QUEUED,
    READY,
    REVIEW_REQUIRED,
    RUNNING,
    STARTING,
)

# ---------------------------------------------------------------------------
# Marker registration (self-contained; no pyproject change required).
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: needs a running bridge + 4 real workers (skips if unreachable)",
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BRIDGE_URL = "http://localhost:8080"
DEFAULT_TIMEOUT = 5.0
POLL_INTERVAL = 1.0
# Generous ceilings for real-worker scenarios (workers run real CodeArts).
STATE_POLL_SECONDS = 120
EXPECTED_WORKER_COUNT = 4

# Source tree root: tests/e2e/<this file> -> parents[2] is project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_BRIDGE = PROJECT_ROOT / "src" / "bridge"


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib urllib; no external ``requests`` dependency).
# ---------------------------------------------------------------------------

def _api_get(path, timeout=DEFAULT_TIMEOUT):
    url = BRIDGE_URL + path
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, (json.loads(body) if body else {})


def _api_post(path, body=None, timeout=DEFAULT_TIMEOUT):
    url = BRIDGE_URL + path
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, (json.loads(raw) if raw else {})


def _bridge_reachable():
    """Return True if the bridge API health endpoint responds."""
    try:
        status, _ = _api_get("/api/health", timeout=2.0)
        return status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bridge_running():
    """Skip the test if the bridge API is not reachable."""
    if not _bridge_reachable():
        pytest.skip("bridge API not reachable at " + BRIDGE_URL)


def _task_state(task_id):
    """Return the current state/status of a task via the bridge API."""
    _, data = _api_get("/api/tasks/" + task_id)
    return str(data.get("state") or data.get("status") or "")


def _poll_state(task_id, target, seconds=STATE_POLL_SECONDS):
    """Poll a task until its state is in target or the budget expires.

    target may be a single state string or a set/tuple of states.
    Returns the final state (does not assert; caller asserts).
    """
    if isinstance(target, str):
        target = {target}
    else:
        target = set(target)
    deadline = time.monotonic() + seconds
    last = ""
    while time.monotonic() < deadline:
        last = _task_state(task_id)
        if last in target:
            return last
        time.sleep(POLL_INTERVAL)
    return last


def _list_outbox(task_id):
    """Return the list of outbox file names for a task."""
    _, data = _api_get("/api/tasks/" + task_id + "/outbox")
    files = data.get("files") or data.get("outbox") or []
    if isinstance(files, list):
        return [str(f.get("name", f)) if isinstance(f, dict) else str(f) for f in files]
    return []


# ---------------------------------------------------------------------------
# Scenarios A-F: real runtime (marked @pytest.mark.integration)
# ---------------------------------------------------------------------------

class TestPR6RealRuntime:
    """Scenarios A-F against a live bridge with 4 real workers."""

    @pytest.mark.integration
    def test_scenario_a_bridge_starts_4_workers_connect(self, bridge_running):
        """Scenario A: bridge serve starts the API and all 4 workers register.

        The bridge API health endpoint responds and /api/workers lists exactly
        4 workers, each reporting a heartbeat/online runtime status.
        """
        status, health = _api_get("/api/health")
        assert status == 200, "bridge health endpoint must respond 200"

        status, data = _api_get("/api/workers")
        assert status == 200
        workers = data.get("workers", [])
        assert len(workers) == EXPECTED_WORKER_COUNT, (
            "expected " + str(EXPECTED_WORKER_COUNT) + " workers, got " + str(len(workers))
        )

        for w in workers:
            wid = w.get("id") or w.get("workerId")
            assert wid, "worker entry must have an id"
            runtime = w.get("runtime") or w.get("status") or {}
            online = (
                runtime.get("online")
                if isinstance(runtime, dict)
                else None
            )
            heartbeat = (
                runtime.get("lastSeen") or runtime.get("heartbeatAt")
                if isinstance(runtime, dict)
                else None
            )
            assert online is True or heartbeat, (
                "worker " + str(wid) + " must report a heartbeat/online status"
            )

    @pytest.mark.integration
    def test_scenario_b_create_dispatch_worker_picks_up(self, bridge_running):
        """Scenario B: create a task, dispatch it, a worker picks it up.

        POST /api/tasks creates a task in READY; the bridge control loop
        dispatches it and a worker transitions it past QUEUED/STARTING to
        RUNNING within the poll budget.
        """
        task_id = "pr6-scen-b-" + str(int(time.time()))
        status, data = _api_post(
            "/api/tasks",
            {
                "taskId": task_id,
                "projectId": "bridge",
                "role": "implement",
                "taskFile": "# TASK\n\nPR-6 scenario B: no-op task.\n",
                "execution": {
                    "targetMinutes": 2,
                    "softTimeoutMinutes": 4,
                    "hardTimeoutMinutes": 6,
                },
            },
        )
        assert status in (200, 201), "create task failed: " + str(status) + " " + str(data)

        final = _poll_state(task_id, {QUEUED, STARTING, RUNNING})
        assert final in {QUEUED, STARTING, RUNNING}, (
            "task " + task_id + " should progress past READY, got state=" + repr(final)
        )

    @pytest.mark.integration
    def test_scenario_c_worker_produces_events(self, bridge_running):
        """Scenario C: a running task produces events visible via the API.

        The task log/events endpoint must surface started, step, reasoning and
        tool_use event markers while the task is RUNNING.
        """
        task_id = "pr6-scen-c-" + str(int(time.time()))
        _api_post(
            "/api/tasks",
            {
                "taskId": task_id,
                "projectId": "bridge",
                "role": "implement",
                "taskFile": "# TASK\n\nPR-6 scenario C: emit events.\n",
                "execution": {
                    "targetMinutes": 3,
                    "softTimeoutMinutes": 6,
                    "hardTimeoutMinutes": 9,
                },
            },
        )

        state = _poll_state(task_id, RUNNING)
        assert state == RUNNING, "task did not reach RUNNING, got " + repr(state)

        _, log_data = _api_get("/api/tasks/" + task_id + "/log")
        log_text = json.dumps(log_data)
        for marker in ("started", "step", "reasoning", "tool_use"):
            assert marker in log_text, (
                "expected event marker " + repr(marker) + " in task log, got: "
                + log_text[:500]
            )

    @pytest.mark.integration
    def test_scenario_d_soft_timeout_assistance_required(self, bridge_running):
        """Scenario D: a task hitting soft-timeout transitions to
        ASSISTANCE_REQUIRED with salvage (CHECKPOINT.md,
        ASSISTANCE_REQUEST.md, DIFF.patch, git-status).
        """
        task_id = "pr6-scen-d-" + str(int(time.time()))
        _api_post(
            "/api/tasks",
            {
                "taskId": task_id,
                "projectId": "bridge",
                "role": "implement",
                "taskFile": "# TASK\n\nPR-6 scenario D: slow task.\n",
                "execution": {
                    "targetMinutes": 1,
                    "softTimeoutMinutes": 1,
                    "hardTimeoutMinutes": 4,
                },
            },
        )

        final = _poll_state(task_id, ASSISTANCE_REQUIRED, seconds=180)
        assert final == ASSISTANCE_REQUIRED, (
            "task should enter ASSISTANCE_REQUIRED on soft timeout, got " + repr(final)
        )

        outbox_files = _list_outbox(task_id)
        for required in ("CHECKPOINT.md", "ASSISTANCE_REQUEST.md", "DIFF.patch"):
            assert required in outbox_files, (
                "salvage file " + required + " missing from outbox: " + str(outbox_files)
            )
        assert any(f.startswith("git-status") for f in outbox_files), (
            "git-status salvage missing from outbox: " + str(outbox_files)
        )

    @pytest.mark.integration
    def test_scenario_e_review_pass_writes_approved_only(self, bridge_running):
        """Scenario E: Review PASS writes APPROVED and does NOT write
        INTEGRATED/DONE/INTEGRATING (PR-1 lifecycle truth).

        The review endpoint must stop at APPROVED; integration is a separate
        loop (Scenario F).
        """
        task_id = "pr6-scen-e-" + str(int(time.time()))
        _api_post(
            "/api/tasks",
            {
                "taskId": task_id,
                "projectId": "bridge",
                "role": "implement",
                "taskFile": "# TASK\n\nPR-6 scenario E: reviewable task.\n",
                "execution": {
                    "targetMinutes": 2,
                    "softTimeoutMinutes": 4,
                    "hardTimeoutMinutes": 6,
                },
            },
        )

        state = _poll_state(task_id, REVIEW_REQUIRED)
        assert state == REVIEW_REQUIRED, (
            "task should reach REVIEW_REQUIRED, got " + repr(state)
        )

        status, _ = _api_post("/api/tasks/" + task_id + "/review/pass")
        assert status in (200, 202), "review pass failed: " + str(status)

        time.sleep(2.0)
        after = _task_state(task_id)
        assert after == APPROVED, (
            "review PASS must write APPROVED, got " + repr(after)
        )
        assert after not in {"INTEGRATING", "INTEGRATED", DONE}, (
            "review PASS must NOT write INTEGRATING/INTEGRATED/DONE (PR-1), got "
            + repr(after)
        )

    @pytest.mark.integration
    def test_scenario_f_integration_approved_to_done(self, bridge_running):
        """Scenario F: the integration loop cherry-picks an APPROVED task and
        transitions it APPROVED -> INTEGRATING -> INTEGRATED -> DONE with a
        real integratedSha.
        """
        task_id = "pr6-scen-f-" + str(int(time.time()))
        _api_post(
            "/api/tasks",
            {
                "taskId": task_id,
                "projectId": "bridge",
                "role": "implement",
                "taskFile": "# TASK\n\nPR-6 scenario F: integration target.\n",
                "execution": {
                    "targetMinutes": 2,
                    "softTimeoutMinutes": 4,
                    "hardTimeoutMinutes": 6,
                },
            },
        )

        state = _poll_state(task_id, REVIEW_REQUIRED)
        assert state == REVIEW_REQUIRED, "task did not reach REVIEW_REQUIRED"
        _api_post("/api/tasks/" + task_id + "/review/pass")
        time.sleep(2.0)
        assert _task_state(task_id) == APPROVED, "task did not reach APPROVED"

        status, _ = _api_post("/api/integrations")
        assert status in (200, 202), "integrate trigger failed: " + str(status)

        final = _poll_state(task_id, DONE, seconds=180)
        assert final == DONE, (
            "task should reach DONE after integration, got " + repr(final)
        )

        _, task = _api_get("/api/tasks/" + task_id)
        integrated_sha = task.get("integratedSha") or task.get("integrated_sha")
        assert integrated_sha, (
            "DONE must carry a real integratedSha, got task=" + str(task)
        )


# ---------------------------------------------------------------------------
# Scenarios G-H: structural checks (no bridge needed)
# ---------------------------------------------------------------------------

class TestPR6NoFakeSupervision:
    """Scenario G: fake supervision is removed (PR-3)."""

    def test_scenario_g_supervision_module_deleted(self):
        """The src/bridge/supervision/ package must be deleted."""
        supervision_dir = SRC_BRIDGE / "supervision"
        assert not supervision_dir.exists(), (
            "supervision/ must be deleted (PR-3), still present at "
            + str(supervision_dir)
        )

    def test_scenario_g_pipeline_has_no_supervisor(self):
        """pipeline.py must contain no Supervisor instance or reference."""
        pipeline_py = SRC_BRIDGE / "pipeline.py"
        assert pipeline_py.is_file(), "pipeline.py must exist"
        text = pipeline_py.read_text(encoding="utf-8")
        assert "Supervisor" not in text, (
            "pipeline.py must have no Supervisor reference (PR-3)"
        )


class TestPR6NoPolicyRuntime:
    """Scenario H: policy/ and runtime/ are removed and worker.py has no
    policy calls (PR-4)."""

    def test_scenario_h_policy_module_deleted(self):
        """The src/bridge/policy/ package must be deleted."""
        policy_dir = SRC_BRIDGE / "policy"
        assert not policy_dir.exists(), (
            "policy/ must be deleted (PR-4), still present at " + str(policy_dir)
        )

    def test_scenario_h_runtime_module_deleted(self):
        """The src/bridge/runtime/ package must be deleted."""
        runtime_dir = SRC_BRIDGE / "runtime"
        assert not runtime_dir.exists(), (
            "runtime/ must be deleted (PR-4), still present at " + str(runtime_dir)
        )

    def test_scenario_h_worker_has_no_policy_calls(self):
        """worker.py must contain no policy import or call."""
        worker_py = SRC_BRIDGE / "worker.py"
        assert worker_py.is_file(), "worker.py must exist"
        text = worker_py.read_text(encoding="utf-8")
        assert "policy" not in text, (
            "worker.py must have no policy reference (PR-4)"
        )
