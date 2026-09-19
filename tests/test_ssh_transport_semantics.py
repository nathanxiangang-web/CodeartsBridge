"""P0: Transport semantics — SshTransport must not inject nested self-SSH directive.

Regression guards for the fix that prevents CodeArts on a worker host from
SSH-ing back to itself to access the project that is already local.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from bridge.codearts import (
    build_worker_core_prompt,
    get_worker_local_access_directive,
    get_remote_access_directive,
)


# ── Directive content tests ──────────────────────────────────────────────────

class TestWorkerLocalDirective:
    def test_contains_local_project_language(self):
        d = get_worker_local_access_directive("/home/nathan/bridge-python")
        assert "already running on the target worker host" in d
        assert "Treat project '/home/nathan/bridge-python' as a LOCAL project directory" in d
        assert "Do not SSH to this worker host" in d

    def test_does_not_contain_remote_ssh_language(self):
        d = get_worker_local_access_directive("/home/nathan/bridge-python")
        assert "The target source is remote" not in d
        assert "non-interactive commands using ssh" not in d
        assert "Run every project inspection, edit, test, and build command over SSH" not in d


class TestRemoteAccessDirective:
    """ssh-shell transport must still get the remote directive."""

    def test_contains_remote_ssh_language(self):
        d = get_remote_access_directive("192.168.178.52", "/home/nathan/bridge-python")
        assert "The target source is remote" in d
        assert "ssh -o BatchMode=yes 192.168.178.52" in d
        assert "Run every project inspection, edit, test, and build command over SSH" in d


# ── Prompt construction tests ────────────────────────────────────────────────

class TestSshTransportPromptSemantics:
    """SshTransport must build a prompt with LOCAL directive, not REMOTE."""

    def _build_prompt(self) -> str:
        project_path = "/home/nathan/bridge-python"
        directive = get_worker_local_access_directive(project_path)
        return build_worker_core_prompt(
            worker_contract="/root/protocol/WORKER.md",
            meta_path="/root/tasks/T1/META.json",
            instructions=["/root/tasks/T1/inbox/TASK.md"],
            outbox_path="/root/tasks/T1/outbox",
            project_path=project_path,
            remote_directive=directive,
        )

    def test_prompt_has_local_directive(self):
        prompt = self._build_prompt()
        assert "already running on the target worker host" in prompt
        assert "as a LOCAL project directory" in prompt
        assert "Do not SSH to this worker host" in prompt

    def test_prompt_no_remote_ssh_directive(self):
        prompt = self._build_prompt()
        assert "The target source is remote" not in prompt
        assert "non-interactive commands using ssh" not in prompt
        assert "Run every project inspection, edit, test, and build command over SSH" not in prompt


class TestSshShellTransportPromptSemantics:
    """SshShellTransport must still use REMOTE directive (regression guard)."""

    def _build_prompt(self) -> str:
        project_path = "/home/nathan/bridge-python"
        directive = get_remote_access_directive("192.168.178.52", project_path)
        return build_worker_core_prompt(
            worker_contract="/root/protocol/WORKER.md",
            meta_path="/root/tasks/T1/META.json",
            instructions=["/root/tasks/T1/inbox/TASK.md"],
            outbox_path="/root/tasks/T1/outbox",
            project_path=project_path,
            remote_directive=directive,
        )

    def test_prompt_has_remote_directive(self):
        prompt = self._build_prompt()
        assert "The target source is remote" in prompt
        assert "ssh -o BatchMode=yes 192.168.178.52" in prompt


# ── SSH command structure test ───────────────────────────────────────────────

class TestSshTransportCommandStructure:
    """SshTransport must only have one layer of SSH (control -> worker).

    The prompt injected into the remote CodeArts must NOT ask the AI to SSH
    back to the worker host.
    """

    def test_ssh_command_has_single_ssh_layer(self):
        """Verify that the SSH command to the worker is a single ssh invocation."""
        from bridge.transport.ssh import SshTransport

        project = MagicMock()
        project.ssh_host = "192.168.178.52"
        project.remote_bridge_root = "/home/nathan/bridge-python"
        project.project_root = "/home/nathan/bridge-python"
        project.remote_cli_path = None

        worker = MagicMock()
        worker.cli_path = "/home/nathan/.codeartsdoer/installers/bin/codearts"

        task_dir = Path("/tmp/test-ssh-semantics")
        transport = SshTransport()

        captured_cmds = []
        original_popen = __import__("subprocess").Popen

        def capture_popen(cmd, *args, **kwargs):
            captured_cmds.append(cmd)
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("", "")
            mock_proc.returncode = 0
            return mock_proc

        def capture_run_captured(cmd, timeout=60):
            captured_cmds.append(cmd)
            return (0, "", "")

        with patch.object(transport, "run_captured", side_effect=capture_run_captured):
            with patch("subprocess.Popen", side_effect=capture_popen):
                try:
                    transport.run(project, worker, task_dir, "T1", timeout_seconds=1)
                except Exception:
                    pass

        # All SSH commands should be single-layer: ssh -o BatchMode=yes <host> <cmd>
        ssh_cmds = [c for c in captured_cmds if isinstance(c, list) and c and c[0] == "ssh"]
        for cmd in ssh_cmds:
            assert "-o" in cmd
            assert "BatchMode=yes" in cmd
            # The command should ssh to the worker host, not contain nested ssh
            cmd_str = " ".join(cmd)
            # Count ssh occurrences — should be exactly 1 (the control ssh)
            assert cmd_str.count("ssh ") == 1, f"Nested SSH detected in: {cmd_str}"