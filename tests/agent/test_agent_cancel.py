"""Tests for Agent cancel."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from bridge.agent.models import JobInfo, JobState
from bridge.agent.store import JobStore
from bridge.agent.runner import Runner


class TestCancel:
    def test_cancel_running_job(self, tmp_path):
        store = JobStore(tmp_path / "agent")
        runner = Runner(store)
        job = JobInfo(
            jobId="cancel-1",
            taskId="T",
            projectRoot=str(tmp_path),
            cliPath="sleep",
            state=JobState.RUNNING.value,
            startedAt=time.time(),
        )
        store.save_job(job)
        job.prompt = "30"
        runner.start(job)

        assert runner.check_process(job) is True
        runner.terminate(job)
        time.sleep(0.5)
        assert runner.check_process(job) is False

    def test_cancel_already_terminal(self, tmp_path):
        store = JobStore(tmp_path / "agent")
        runner = Runner(store)
        job = JobInfo(
            jobId="cancel-2",
            taskId="T",
            state=JobState.COMPLETED.value,
        )
        store.save_job(job)
        runner.terminate(job)