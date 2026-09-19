"""Tests for Agent HTTP API — health, create/get/cancel job, auth."""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.request
import urllib.error
from pathlib import Path

import pytest

from bridge.agent.server import AgentServer
from bridge.agent.config import AgentConfig
from bridge.agent.auth import generate_token, compare_token, check_auth, AuthError, extract_bearer


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def agent_server(tmp_path):
    port = _find_free_port()
    config = AgentConfig()
    config.allowed_roots = [str(tmp_path)]
    server = AgentServer(
        host="127.0.0.1",
        port=port,
        data_root=tmp_path / "agent-data",
        config=config,
        token="test-token-12345",
    )
    server_thread = __import__("threading").Thread(target=server.start, daemon=True)
    server_thread.start()
    time.sleep(0.5)
    yield server
    server.stop()


def _get(server, path, token="test-token-12345"):
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _post(server, path, body, token="test-token-12345"):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class TestHealth:
    def test_health_no_auth_required(self, agent_server):
        code, data = _get(agent_server, "/v1/health", token="")
        assert code == 200
        assert data["ok"] is True
        assert "agentVersion" in data
        assert "hostname" in data
        assert "capacity" in data

    def test_health_returns_active_jobs(self, agent_server):
        code, data = _get(agent_server, "/v1/health")
        assert code == 200
        assert data["activeJobs"] == 0


class TestAuth:
    def test_missing_auth_rejected(self, agent_server):
        try:
            _get(agent_server, "/v1/jobs/test", token="")
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 401

    def test_wrong_token_rejected(self, agent_server):
        try:
            _get(agent_server, "/v1/jobs/test", token="wrong")
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 401

    def test_correct_token_accepted(self, agent_server):
        try:
            code, data = _get(agent_server, "/v1/jobs/nonexistent")
            assert code == 404
        except urllib.error.HTTPError as e:
            assert e.code == 404


class TestTokenFunctions:
    def test_generate_token_unique(self):
        t1 = generate_token()
        t2 = generate_token()
        assert t1 != t2
        assert len(t1) > 20

    def test_compare_token(self):
        assert compare_token("abc", "abc") is True
        assert compare_token("abc", "def") is False
        assert compare_token("", "abc") is False

    def test_extract_bearer(self):
        assert extract_bearer({"Authorization": "Bearer xyz"}) == "xyz"
        assert extract_bearer({"Authorization": "Basic xyz"}) is None
        assert extract_bearer({}) is None

    def test_check_auth_raises(self):
        with pytest.raises(AuthError):
            check_auth({}, "expected")
        with pytest.raises(AuthError):
            check_auth({"Authorization": "Bearer wrong"}, "expected")


class TestJobLifecycle:
    def test_get_nonexistent_job(self, agent_server):
        try:
            code, data = _get(agent_server, "/v1/jobs/nonexistent")
        except urllib.error.HTTPError as e:
            assert e.code == 404

    def test_cancel_nonexistent_job(self, agent_server):
        try:
            _post(agent_server, "/v1/jobs/nonexistent/cancel", {})
        except urllib.error.HTTPError as e:
            assert e.code == 404

    def test_events_nonexistent_job(self, agent_server):
        code, data = _get(agent_server, "/v1/jobs/nonexistent/events?cursor=0")
        assert code == 200
        assert data["events"] == []

    def test_artifacts_nonexistent_job(self, agent_server):
        try:
            _get(agent_server, "/v1/jobs/nonexistent/artifacts")
        except urllib.error.HTTPError as e:
            assert e.code == 404