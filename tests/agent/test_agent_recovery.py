"""Tests for Agent recovery — daemon restart."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from bridge.agent.models import JobInfo, JobState
from bridge.agent.store import JobStore
from bridge.agent.runner import Runner
from bridge.agent.recovery import Recovery


class TestRecovery:
    def test_reconcile_terminal_skipped(self, tmp_path):
        store = JobStore(tmp_path / "agent")
        runner = Runner(store)
        recovery = Recovery(store, runner)

        job = JobInfo(
            jobId="rec-1",
            taskId="T",
            state=JobState.COMPLETED.value,
        )
        store.save_job(job)
        result = recovery.reconcile()
        assert len(result) == 0

    def test_reconcile_orphan_converged(self, tmp_path):
        store = JobStore(tmp_path / "agent")
        runner = Runner(store)
        recovery = Recovery(store, runner)

        job = JobInfo(
            jobId="rec-2",
            taskId="T",
            state=JobState.RUNNING.value,
            pid=999999,
            startedAt=time.time() - 60,
        )
        store.save_job(job)
        result = recovery.reconcile()
        assert len(result) == 1
        loaded = store.load_job("rec-2")
        assert JobState(loaded.state).is_terminal