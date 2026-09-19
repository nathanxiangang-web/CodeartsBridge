"""Tests for AgentTransport — Bridge side integration."""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bridge.transport.agent import AgentTransport
from bridge.transport.base import TransportResult


class TestAgentTransport:
    def test_missing_endpoint_returns_error(self):
        transport = AgentTransport()
        project = MagicMock()
        worker = MagicMock()
        worker.endpoint = None
        worker.agent_endpoint = None
        result = transport.run(project, worker, "/tmp", "T1")
        assert result.exit_code == -1
        assert "endpoint" in result.stderr

    def test_build_prompt(self, tmp_path):
        transport = AgentTransport()
        project = MagicMock()
        project.project_root = str(tmp_path)

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "TASK.md").write_text("# Task")

        prompt = transport._build_prompt(tmp_path, project)
        assert "LOCAL" in prompt or "local" in prompt
        assert "=== TASK.md ===" in prompt
        assert "# Task" in prompt
        assert "CODEARTS_OUTBOX" in prompt

    def test_poll_job_completed(self):
        transport = AgentTransport()
        mock_responses = [
            {"state": "RUNNING", "exitCode": None},
            {"state": "COMPLETED", "exitCode": 0},
        ]
        call_count = [0]

        def mock_get(url, token):
            idx = min(call_count[0], len(mock_responses) - 1)
            call_count[0] += 1
            return mock_responses[idx]

        with patch.object(transport, "_get", side_effect=mock_get):
            result = transport._poll_job("http://localhost:8765", "token", "job-1", 60)
        assert result.exit_code == 0

    def test_poll_job_timed_out(self):
        transport = AgentTransport()
        with patch.object(transport, "_get", return_value={"state": "TIMED_OUT", "exitCode": -1}):
            result = transport._poll_job("http://localhost:8765", "token", "job-1", 60)
        assert result.timed_out is True
        assert result.assistance_requested is True

    def test_poll_job_cancelled(self):
        transport = AgentTransport()
        with patch.object(transport, "_get", return_value={"state": "CANCELLED", "exitCode": -1}):
            result = transport._poll_job("http://localhost:8765", "token", "job-1", 60)
        assert result.cancelled is True