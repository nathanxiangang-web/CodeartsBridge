# AI生成
"""CodeArts CLI wrapper: argument construction, JSONL event parsing, session reuse.

Mirrors PowerShell Find-CodeArtsCli, New-WorkerRunArguments, Parse-CodeArtsJsonLines,
Build-WorkerCorePrompt, Get-ModeFlag, Get-RemoteAccessDirective.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

REQUIRED_MODEL = "huaweicloud-maas/GLM-5.2"
THINK_LANGUAGE_DIRECTIVE = (
    "Use English for all reasoning, analysis, tool summaries, console-visible event text, "
    "and final output. Do not emit Chinese text in Worker-generated content because "
    "non-ASCII console output may be corrupted."
)


def find_codearts_cli() -> str | None:
    """Find the codearts CLI binary."""
    path = shutil.which("codearts")
    if path:
        return path
    candidates = [
        Path.home() / ".codeartsdoer/installers/bin/codearts",
        Path("/usr/local/bin/codearts"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def get_mode_flag(mode: str) -> str | None:
    if mode == "auto":
        return "--auto"
    elif mode == "sandbox":
        return "--sandbox"
    elif mode == "manual":
        return None
    else:
        raise ValueError(f"Unsupported run mode: {mode}")


def new_worker_run_arguments(
    prompt: str,
    model: str | None = None,
    mode_flag: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
) -> list[str]:
    """Build codearts CLI argument list. Matches New-WorkerRunArguments."""
    args = ["run", prompt, "--format", "json", "--thinking"]
    if session_id:
        args += ["--session", session_id]
    else:
        if not task_id:
            raise ValueError("TaskId must not be empty")
        args += ["--title", task_id]
    if model:
        args += ["-m", model]
    if mode_flag:
        args.append(mode_flag)
    return args


def build_worker_core_prompt(
    worker_contract: str,
    meta_path: str,
    instructions: list[str],
    outbox_path: str,
    project_path: str,
    remote_directive: str = "",
    directive: str = THINK_LANGUAGE_DIRECTIVE,
) -> str:
    """Build the worker prompt. Matches Build-WorkerCorePrompt."""
    list_segment = ", ".join(f"'{p}'" for p in instructions)
    latest = instructions[-1]
    base = (
        f"You are a GLM Worker. Read '{worker_contract}', '{meta_path}', "
        f"and every instruction file in this task inbox in order: {list_segment}. "
        f"Treat '{latest}' as the latest instruction while preserving the full context "
        f"of all earlier TASK/FIX files. Work autonomously inside project '{project_path}'."
    )
    if remote_directive:
        base += f" {remote_directive}"
    base += (
        f" Write the formal deliverables to '{outbox_path}'; do not return them only in chat. "
        f"If the built-in editor refuses to write to the outbox, use the current system shell "
        f"to write the files there. {directive}"
    )
    return base


def get_remote_access_directive(host_name: str, remote_project_path: str) -> str:
    return (
        f"The target source is remote. Access project '{remote_project_path}' only through "
        f"non-interactive commands using ssh -o BatchMode=yes {host_name}. "
        f"Do not seek, read, record, or transfer passwords, tokens, access keys, secret keys, "
        f"private keys, or .env content. Run every project inspection, edit, test, and build "
        f"command over SSH inside that remote project. Do not copy source into the bridge directory."
    )


def parse_codearts_json_lines(output: str) -> dict:
    """Parse CodeArts JSONL stdout for session ID, last event time, and tokens.

    Matches Parse-CodeArtsJsonLines.
    """
    session_id = None
    last_event_at = None
    tokens = None

    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not event or not isinstance(event, dict):
            continue

        # Extract session ID
        sid = event.get("sessionID") or event.get("sessionId")
        if not sid and isinstance(event.get("session"), dict):
            sid = event["session"].get("id")
        if sid and not session_id:
            session_id = str(sid)

        # Extract timestamp
        ts = event.get("timestamp") or event.get("time") or event.get("ts") or event.get("datetime")
        if ts:
            last_event_at = str(ts)

        # Extract tokens from step_finish
        t = None
        if isinstance(event.get("step_finish"), dict):
            sf = event["step_finish"]
            if isinstance(sf.get("part"), dict) and "tokens" in sf["part"]:
                t = sf["part"]["tokens"]
        if not t and event.get("type") == "step_finish" and isinstance(event.get("part"), dict):
            if "tokens" in event["part"]:
                t = event["part"]["tokens"]
        if t:
            tokens = t

    return {"sessionId": session_id, "lastEventAt": last_event_at, "tokens": tokens}


def sensitive_mask(text: str) -> str:
    """Mask sensitive information in text for display. Matches Invoke-SensitiveMask."""
    text = re.sub(r"CODEARTS_CLI_AK=\S+", "CODEARTS_CLI_AK=***", text)
    text = re.sub(r"CODEARTS_CLI_SK=\S+", "CODEARTS_CLI_SK=***", text)
    text = re.sub(r"(?i)Bearer\s+\S+", "Bearer ***", text)
    text = re.sub(r"(?i)(password|token|secret|api_key)=\S+", r"\1=***", text)
    return text