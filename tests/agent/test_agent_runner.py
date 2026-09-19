"""Tests for Agent runner — local process execution via argv."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from bridge.agent.models import JobInfo, JobState, LogEvent
from bridge.agent.store import JobStore
from bridge.agent.runner import Runner


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "agent")


@pytest.fixture
def runner(store):
    return Runner(store)


class TestRunner:
    def test_start_process(self, store, runner, tmp_path):
        job = JobInfo(
            jobId="test-1",
            taskId="T1",
            projectRoot=str(tmp_path),
            cliPath="echo",
            model="test",
            mode="auto",
        )
        store.save_job(job)
        job.prompt = "hello"
        pid, pgid = runner.start(job)
        assert pid > 0
        assert pgid > 0

        time.sleep(0.5)
        loaded = store.load_job("test-1")
        assert loaded.state == JobState.RUNNING.value
        assert loaded.pid == pid

    def test_check_process_alive(self, store, runner, tmp_path):
        job = JobInfo(
            jobId="test-2",
            taskId="T2",
            projectRoot=str(tmp_path),
            cliPath="sleep",
            model="test",
        )
        store.save_job(job)
        job.prompt = "5"
        pid, pgid = runner.start(job)
        assert runner.check_process(job) is True

        import signal
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        time.sleep(0.5)
        assert runner.check_process(job) is False

    def test_terminate_process(self, store, runner, tmp_path):
        job = JobInfo(
            jobId="test-3",
            taskId="T3",
            projectRoot=str(tmp_path),
            cliPath="sleep",
            model="test",
        )
        store.save_job(job)
        job.prompt = "30"
        pid, pgid = runner.start(job)
        assert runner.check_process(job) is True

        runner.terminate(job)
        time.sleep(0.5)
        assert runner.check_process(job) is False

    def test_build_args(self, store, runner, tmp_path):
        job = JobInfo(
            jobId="test-4",
            taskId="T4",
            projectRoot=str(tmp_path),
            cliPath="codearts",
            model="GLM-5.2",
            mode="auto",
            sessionId="ses-123",
        )
        args = runner._build_args(job)
        assert "run" in args
        assert "--model" in args
        assert "GLM-5.2" in args
        assert "--session" in args
        assert "ses-123" in args