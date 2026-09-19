"""Tests for Agent recovery — daemon restart."""
from __future__ import annotations

import os
import subprocess
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

    def test_reconcile_live_orphan_is_terminated_not_fake_reattached(self, tmp_path):
        store = JobStore(tmp_path / "agent")
        runner = Runner(store)
        recovery = Recovery(store, runner)

        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            job = JobInfo(
                jobId="rec-live",
                taskId="T",
                state=JobState.RUNNING.value,
                pid=proc.pid,
                startedAt=time.time() - 5,
            )
            store.save_job(job)
            store.save_process_info("rec-live", proc.pid, os.getpgid(proc.pid))

            result = recovery.reconcile()
            assert len(result) == 1

            proc.wait(timeout=5)
            loaded = store.load_job("rec-live")
            assert loaded is not None
            assert loaded.state == JobState.ASSISTANCE_REQUIRED.value
            assert loaded.exitCode == -1

            _, events = store.read_events("rec-live", 0)
            assert any("cannot be re-attached" in e.text for e in events)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

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