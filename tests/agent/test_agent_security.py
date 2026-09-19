"""Tests for the remaining optional Agent auth/path helpers.

The Local-First refactor intentionally removed project-root allowlists from the
runtime path.  Do not reintroduce allowlist tests: Agent accepts the projectRoot
chosen by the trusted Bridge and fails only if execution itself cannot use it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bridge.agent.auth import check_auth, AuthError, compare_token, generate_token
from bridge.agent.fs_guard import validate_path, is_safe_write_path, FsGuardError


class TestAuth:
    def test_generate_token_length(self):
        t = generate_token()
        assert len(t) > 20

    def test_compare_token_timing_safe(self):
        assert compare_token("a" * 32, "a" * 32) is True
        assert compare_token("a" * 32, "b" * 32) is False

    def test_check_auth_no_token_configured(self):
        with pytest.raises(AuthError, match="no token"):
            check_auth({"Authorization": "Bearer x"}, "")

    def test_check_auth_missing_header(self):
        with pytest.raises(AuthError, match="Missing"):
            check_auth({}, "expected")

    def test_check_auth_invalid_token(self):
        with pytest.raises(AuthError, match="Invalid"):
            check_auth({"Authorization": "Bearer wrong"}, "expected")


class TestFsGuard:
    def test_valid_path(self, tmp_path):
        result = validate_path(tmp_path, "src/main.py")
        assert str(result).startswith(str(tmp_path))

    def test_path_traversal_blocked(self, tmp_path):
        with pytest.raises(FsGuardError, match="escapes"):
            validate_path(tmp_path, "../../etc/passwd")

    def test_absolute_path_blocked(self, tmp_path):
        with pytest.raises(FsGuardError, match="escapes"):
            validate_path(tmp_path, "/etc/passwd")

    def test_ssh_dir_blocked(self):
        assert is_safe_write_path(Path("/home/user/.ssh/id_rsa")) is False

    def test_env_file_blocked(self):
        assert is_safe_write_path(Path("/home/user/.env")) is False

    def test_normal_path_allowed(self):
        assert is_safe_write_path(Path("/home/user/project/src/main.py")) is True
