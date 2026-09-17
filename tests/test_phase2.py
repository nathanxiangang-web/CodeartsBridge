# AI生成
"""Tests for Phase 2: codearts, git_ops, transport."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bridge.codearts import (
    find_codearts_cli, get_mode_flag, new_worker_run_arguments,
    build_worker_core_prompt, get_remote_access_directive,
    parse_codearts_json_lines, sensitive_mask, REQUIRED_MODEL,
)
from bridge.git_ops import quote_posix, remote_worker_guardrail_prefix, is_git_repo
from bridge.transport import (
    TransportResult, LocalTransport, SshTransport,
    SshShellTransport, RemoteWorktreeTransport,
)


class TestCodeArts:
    def test_get_mode_flag(self):
        assert get_mode_flag("auto") == "--auto"
        assert get_mode_flag("sandbox") == "--sandbox"
        assert get_mode_flag("manual") is None
        try:
            get_mode_flag("invalid")
            assert False
        except ValueError:
            pass

    def test_new_worker_run_arguments_new_session(self):
        args = new_worker_run_arguments(
            prompt="test prompt", model="GLM-5.2",
            mode_flag="--auto", task_id="task-001",
        )
        assert args[0] == "run"
        assert args[1] == "test prompt"
        assert "--format" in args
        assert "json" in args
        assert "--thinking" in args
        assert "--title" in args
        assert "task-001" in args
        assert "-m" in args
        assert "GLM-5.2" in args
        assert "--auto" in args

    def test_new_worker_run_arguments_resume(self):
        args = new_worker_run_arguments(
            prompt="test", task_id="task-001", session_id="abc-123",
        )
        assert "--session" in args
        assert "abc-123" in args
        assert "--title" not in args

    def test_build_worker_core_prompt(self):
        prompt = build_worker_core_prompt(
            worker_contract="/path/WORKER.md",
            meta_path="/task/META.json",
            instructions=["/task/inbox/001-TASK.md"],
            outbox_path="/task/outbox",
            project_path="/project",
        )
        assert "GLM Worker" in prompt
        assert "/path/WORKER.md" in prompt
        assert "/task/META.json" in prompt
        assert "/project" in prompt
        assert "/task/outbox" in prompt

    def test_parse_json_lines(self):
        jsonl = '{"sessionID": "sess-123", "timestamp": "2024-01-01T00:00:00Z"}\n{"type": "step_finish", "part": {"tokens": 500}}'
        result = parse_codearts_json_lines(jsonl)
        assert result["sessionId"] == "sess-123"
        assert result["tokens"] == 500

    def test_parse_json_lines_empty(self):
        result = parse_codearts_json_lines("")
        assert result["sessionId"] is None
        assert result["lastEventAt"] is None
        assert result["tokens"] is None

    def test_sensitive_mask(self):
        text = "CODEARTS_CLI_AK=AK123456 CODEARTS_CLI_SK=SK789 token=abc123"
        masked = sensitive_mask(text)
        assert "AK123456" not in masked
        assert "SK789" not in masked
        assert "abc123" not in masked
        assert "***" in masked

    def test_find_cli(self):
        # Just verify it doesn't crash
        result = find_codearts_cli()
        assert result is None or isinstance(result, str)


class TestGitOps:
    def test_quote_posix_simple(self):
        assert quote_posix("hello") == "'hello'"

    def test_quote_posix_with_quote(self):
        result = quote_posix("it's")
        assert "'\"'\"'" in result

    def test_quote_posix_control_chars(self):
        try:
            quote_posix("hello\nworld")
            assert False
        except ValueError:
            pass

    def test_guardrail_prefix(self):
        prefix = remote_worker_guardrail_prefix()
        assert "GIT_TERMINAL_PROMPT=0" in prefix
        assert "unset" in prefix
        assert "SSH_AUTH_SOCK" in prefix

    def test_is_git_repo(self, tmp_path):
        assert not is_git_repo(tmp_path)


class TestTransport:
    def test_transport_result_defaults(self):
        r = TransportResult()
        assert r.exit_code is None
        assert r.stdout == ""
        assert r.timed_out is False
        assert r.cancelled is False

    def test_transport_classes_exist(self):
        assert LocalTransport is not None
        assert SshTransport is not None
        assert SshShellTransport is not None
        assert RemoteWorktreeTransport is not None

    def test_local_transport_instantiation(self):
        t = LocalTransport()
        assert isinstance(t, LocalTransport)

    def test_ssh_transport_instantiation(self):
        t = SshTransport()
        assert isinstance(t, SshTransport)

    def test_remote_worktree_instantiation(self):
        t = RemoteWorktreeTransport()
        assert isinstance(t, RemoteWorktreeTransport)