# AI生成
"""Shared fixtures for E2E tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def bridge_root(tmp_path: Path) -> Path:
    """Create a temporary bridge root with layout."""
    root = tmp_path / "bridge"
    for d in ("tasks", "runtime", "runtime/locks", "runtime/leases",
              "runtime/worktrees", "runtime/logs", "archive", "work"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def projects_json(bridge_root: Path) -> Path:
    """Write a minimal projects.json."""
    data = {
        "schemaVersion": 1,
        "defaults": {"runMode": "auto", "model": "test-model", "timeoutMinutes": 5},
        "projects": [
            {"id": "test-local", "transport": "local", "projectRoot": str(bridge_root / "work"), "runMode": "auto"},
            {"id": "test-remote", "transport": "remote-worktree", "projectRoot": "/remote/repo",
             "sshHost": "user@host", "remoteWorkspaceRoot": "/remote/ws", "runMode": "auto"},
        ],
    }
    p = bridge_root / "projects.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def workers_json(bridge_root: Path) -> Path:
    """Write a minimal workers.json."""
    data = {
        "schemaVersion": 1,
        "defaults": {"model": "test-model", "concurrencyLimit": 1, "enabled": True},
        "workers": [
            {"id": "w1", "transport": "local", "concurrencyLimit": 1,
             "enabled": True, "capabilities": ["implement", "review", "test"]},
            {"id": "w2", "transport": "ssh", "host": "user@host2", "concurrencyLimit": 1,
             "enabled": True, "capabilities": ["implement", "review", "test"]},
            {"id": "w3", "transport": "ssh", "host": "user@host3", "concurrencyLimit": 1,
             "enabled": True, "capabilities": ["implement", "review", "test"]},
            {"id": "w4-qa", "transport": "ssh", "host": "user@host4", "concurrencyLimit": 1,
             "enabled": True, "capabilities": ["review", "test"]},
        ],
    }
    p = bridge_root / "workers.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def setup_bridge(bridge_root, projects_json, workers_json):
    """Full bridge setup with projects and workers."""
    return bridge_root