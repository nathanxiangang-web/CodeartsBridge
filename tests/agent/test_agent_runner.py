"""Tests for Agent runner live event streaming."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from bridge.agent.models import JobInfo, JobState
from bridge.agent.store import JobStore
from bridge.agent.runner import Runner, _parse_codearts_line, _probe_cli, _resolve_cli_path


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "agent")


@pytest.fixture
def runner(store):
    return Runner(store)


def _fake_cli(tmp_path: Path) -> str:
    path = tmp_path / "fake-codearts"
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys
import time

print(json.dumps({
    "type": "reasoning",
    "timestamp": time.time(),
    "part": {"text": "inspect project"}
}), flush=True)
print(json.dumps({
    "type": "tool_use",
    "timestamp": time.time(),
    "part": {
        "tool": "read",
        "state": {"input": {"filePath": "/tmp/main.py"}}
    }
}), flush=True)
if "SLEEP_LONG" in sys.argv:
    time.sleep(10)
else:
    time.sleep(0.15)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return str(path)


def _tty_sensitive_fake_cli(tmp_path: Path) -> str:
    """Model CodeArts JSON mode: machine output is emitted only to a pipe."""
    path = tmp_path / "fake-codearts-tty-sensitive"
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys
import time

if sys.stdout.isatty():
    # This is the regression we saw on real workers: forcing a PTY can keep
    # the process alive without producing the JSON stream Bridge expects.
    time.sleep(3)
else:
    print(json.dumps({
        "type": "reasoning",
        "timestamp": time.time(),
        "part": {"text": "json pipe active"}
    }), flush=True)
    time.sleep(0.1)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return str(path)


def _job(tmp_path: Path, cli: str, job_id: str, prompt: str = "hello") -> JobInfo:
    return JobInfo(
        jobId=job_id,
        taskId=job_id,
        projectRoot=str(tmp_path),
        cliPath=cli,
        model="GLM-5.2",
        mode="auto",
        prompt=prompt,
    )


def _wait_for_events(store: JobStore, job_id: str, minimum: int = 3) -> list:
    deadline = time.time() + 5
    events = []
    while time.time() < deadline:
        _, events = store.read_events(job_id, 0)
        if len(events) >= minimum:
            return events
        time.sleep(0.05)
    return events


class TestCliHealth:
    def test_probe_kills_hung_cli(self, tmp_path):
        cli = tmp_path / "hung-codearts"
        cli.write_text(
            "#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n",
            encoding="utf-8",
        )
        cli.chmod(0o755)

        started = time.monotonic()
        with pytest.raises(RuntimeError, match="--version.*timed out"):
            _probe_cli(str(cli), timeout_seconds=0.1)
        assert time.monotonic() - started < 2

    def test_resolve_prefers_official_user_install(self, tmp_path, monkeypatch):
        installers = tmp_path / ".codeartsdoer" / "installers" / "bin"
        installers.mkdir(parents=True)
        official = installers / "codearts"
        official.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        official.chmod(0o755)

        monkeypatch.setattr("bridge.agent.runner.Path.home", lambda: tmp_path)
        monkeypatch.setattr("bridge.agent.runner.shutil.which", lambda _: "/usr/local/bin/codearts")

        assert _resolve_cli_path("codearts") == str(official)


class TestRunner:
    def test_start_process_streams_reasoning_and_tool_events(self, store, runner, tmp_path):
        cli = _fake_cli(tmp_path)
        job = _job(tmp_path, cli, "test-stream")
        store.save_job(job)

        pid, pgid = runner.start(job)
        assert pid > 0
        assert pgid > 0

        events = _wait_for_events(store, job.jobId)
        types = [e.type for e in events]
        assert "started" in types
        assert "reasoning" in types
        assert "tool" in types

        ids = [e.id for e in events]
        assert len(ids) == len(set(ids)), "UI event ids must not collide"

        session_log = store.job_dir(job.jobId) / "session.log"
        deadline = time.time() + 3
        while time.time() < deadline and (not session_log.exists() or session_log.stat().st_size == 0):
            time.sleep(0.05)
        assert session_log.exists()
        assert "reasoning" in session_log.read_text(encoding="utf-8", errors="replace")

    def test_json_mode_does_not_force_child_stdout_to_tty(self, store, runner, tmp_path):
        cli = _tty_sensitive_fake_cli(tmp_path)
        job = _job(tmp_path, cli, "test-json-pipe")
        store.save_job(job)

        runner.start(job)
        events = _wait_for_events(store, job.jobId, minimum=2)

        reasoning = [e for e in events if e.type == "reasoning"]
        assert reasoning, "CodeArts JSON output disappeared because stdout became a TTY"
        assert reasoning[0].text == "json pipe active"

        session_log = store.job_dir(job.jobId) / "session.log"
        deadline = time.time() + 2
        while time.time() < deadline and (
            not session_log.exists() or session_log.stat().st_size == 0
        ):
            time.sleep(0.05)
        assert session_log.stat().st_size > 0

        saved = store.load_job(job.jobId)
        assert saved is not None
        assert saved.lastEventAt >= saved.startedAt

    def test_check_process_alive_and_terminate(self, store, runner, tmp_path):
        cli = _fake_cli(tmp_path)
        job = _job(tmp_path, cli, "test-alive", prompt="SLEEP_LONG")
        store.save_job(job)

        _, pgid = runner.start(job)
        assert runner.check_process(job) is True

        runner.terminate(job, grace_seconds=0)
        deadline = time.time() + 3
        while time.time() < deadline and runner.check_process(job):
            time.sleep(0.05)
        assert runner.check_process(job) is False
        assert runner.get_exit_code(job) is not None

    def test_build_args_matches_codearts_json_mode(self, runner, tmp_path):
        job = JobInfo(
            jobId="test-args",
            taskId="T4",
            projectRoot=str(tmp_path),
            cliPath="codearts",
            model="GLM-5.2",
            mode="auto",
            sessionId="ses-123",
            prompt="do work",
        )
        args = runner._build_args(job)
        assert args[:2] == ["run", "do work"]
        assert "--format" in args
        assert "json" in args
        assert "--thinking" in args
        assert "--auto" in args
        assert "-m" in args
        assert "GLM-5.2" in args
        assert "--session" in args
        assert "ses-123" in args

    def test_parse_codearts_line(self):
        parsed = _parse_codearts_line(
            '{"type":"tool_use","part":{"tool":"bash","state":{"input":{"command":"pytest -q"}}}}'
        )
        assert parsed == ("tool", "bash pytest -q")
