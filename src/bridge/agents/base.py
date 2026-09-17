# AI生成
"""Agent adapter base class.

An agent adapter translates bridge-internal task descriptions into
the concrete command-line invocation for a specific AI coding agent
(CodeArts, Claude Code, etc.). The core never imports agent-specific
logic directly — it always goes through an AgentAdapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentRunRequest:
    """Everything an adapter needs to build a command."""
    task_id: str
    worker_id: str
    prompt: str
    model: str = ""
    run_mode: str = "auto"  # auto, sandbox, manual
    session_id: str = ""
    project_path: str = ""
    meta_path: str = ""
    outbox_path: str = ""
    worker_contract_path: str = ""
    instruction_files: list[str] = field(default_factory=list)
    remote_directive: str = ""
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class AgentRunCommand:
    """The command to execute and its environment."""
    command: list[str]
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)


class AgentAdapter(ABC):
    """Abstract base for agent adapters."""

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Return the agent type identifier (e.g. 'codearts')."""
        ...

    @abstractmethod
    def find_cli(self) -> str | None:
        """Locate the agent CLI binary. Return path or None."""
        ...

    @abstractmethod
    def build_command(self, request: AgentRunRequest) -> AgentRunCommand:
        """Build the command-line invocation for the agent."""
        ...

    def parse_output(self, output: str) -> dict:
        """Parse agent stdout for session/tokens/etc. Override if needed."""
        return {}

    def is_available(self) -> bool:
        """Check if the agent CLI is available."""
        return self.find_cli() is not None
