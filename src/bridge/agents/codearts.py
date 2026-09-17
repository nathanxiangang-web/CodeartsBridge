# AI生成
"""CodeArts agent adapter.

Wraps the existing codearts.py CLI logic behind the AgentAdapter interface,
so the core/scheduler/runtime never import CodeArts-specific functions directly.
"""

from __future__ import annotations

from pathlib import Path

from .base import AgentAdapter, AgentRunRequest, AgentRunCommand
from ..codearts import (
    find_codearts_cli,
    get_mode_flag,
    new_worker_run_arguments,
    build_worker_core_prompt,
    get_remote_access_directive,
    parse_codearts_json_lines,
    sensitive_mask,
    REQUIRED_MODEL,
)


class CodeArtsAdapter(AgentAdapter):
    """Adapter for the CodeArts CLI agent."""

    @property
    def agent_type(self) -> str:
        return "codearts"

    def find_cli(self) -> str | None:
        return find_codearts_cli()

    def build_command(self, request: AgentRunRequest) -> AgentRunCommand:
        """Build the CodeArts CLI command from a run request."""
        cli_path = self.find_cli()
        if cli_path is None:
            raise RuntimeError("CodeArts CLI not found")

        # Build the prompt if not pre-built
        prompt = request.prompt
        if not prompt and request.worker_contract_path:
            remote_directive = request.remote_directive
            if not remote_directive and request.project_path:
                # Prompt is pre-built by caller in most cases
                pass
            prompt = build_worker_core_prompt(
                worker_contract=request.worker_contract_path,
                meta_path=request.meta_path,
                instructions=request.instruction_files,
                outbox_path=request.outbox_path,
                project_path=request.project_path,
                remote_directive=remote_directive,
            )

        # Determine model
        model = request.model or REQUIRED_MODEL

        # Determine mode flag
        mode_flag = get_mode_flag(request.run_mode)

        # Build argument list
        args = new_worker_run_arguments(
            prompt=prompt,
            model=model,
            mode_flag=mode_flag,
            task_id=request.task_id,
            session_id=request.session_id,
        )

        command = [cli_path] + args

        # Set up environment with auth keys if provided
        env = dict(request.env)

        cwd = Path(request.project_path) if request.project_path else None

        return AgentRunCommand(command=command, cwd=cwd, env=env)

    def parse_output(self, output: str) -> dict:
        """Parse CodeArts JSONL stdout."""
        return parse_codearts_json_lines(output)

    def mask_sensitive(self, text: str) -> str:
        """Mask sensitive information in text."""
        return sensitive_mask(text)
