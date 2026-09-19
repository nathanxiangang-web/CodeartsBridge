"""Tests for Agent timeout — soft and hard."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from bridge.agent.models import JobInfo, JobState
from bridge.agent.store import JobStore
from bridge.agent.runner import Runner
from bridge.agent.watchdog import Watchdog


@pytest.fixture
def watchdog(tmp_path):
    store = JobStore(tmp_path / "agent")
    runner = Runner(store)
    return Watchdog(store, runner), store


class TestSoftTimeout:
    def test_soft_timeout_reached(self, watchdog, tmp_path):
        wd, store = watchdog
        job = JobInfo(
            jobId="t-soft",
            taskId="T",
            projectRoot=str(tmp_path),
            state=JobState.RUNNING.value,
            startedAt=time.time() - 10,
            softTimeoutSeconds=5,
            hardTimeoutSeconds=100,
        )
        store.save_job(job)
        result = wd.check_timeouts(job)
        assert result == JobState.SOFT_LIMIT

        loaded = store.load_job("t-soft")
        assert loaded.softLimitReached is True
        assert loaded.state == JobState.SOFT_LIMIT.value

    def test_soft_timeout_not_yet(self, watchdog, tmp_path):
        wd, store = watchdog
        job = JobInfo(
            jobId="t-soft-not",
            taskId="T",
            projectRoot=str(tmp_path),
            state=JobState.RUNNING.value,
            startedAt=time.time(),
            softTimeoutSeconds=100,
            hardTimeoutSeconds=200,
        )
        store.save_job(job)
        result = wd.check_timeouts(job)
        assert result is None


class TestHardTimeout:
    def test_hard_timeout_no_deliverables(self, watchdog, tmp_path):
        wd, store = watchdog
        job = JobInfo(
            jobId="t-hard",
            taskId="T",
            projectRoot=str(tmp_path),
            state=JobState.RUNNING.value,
            startedAt=time.time() - 100,
            softTimeoutSeconds=5,
            hardTimeoutSeconds=10,
        )
        store.save_job(job)
        result = wd.check_timeouts(job)
        assert result in (JobState.TIMED_OUT, JobState.ASSISTANCE_REQUIRED)

    def test_hard_timeout_terminal_skipped(self, watchdog, tmp_path):
        wd, store = watchdog
        job = JobInfo(
            jobId="t-terminal",
            taskId="T",
            projectRoot=str(tmp_path),
            state=JobState.COMPLETED.value,
            startedAt=time.time() - 100,
            softTimeoutSeconds=5,
            hardTimeoutSeconds=10,
        )
        store.save_job(job)
        result = wd.check_timeouts(job)
        assert result is None