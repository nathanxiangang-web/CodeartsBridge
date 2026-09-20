# AI生成
"""Config loading for projects.json and workers.json.

Mirrors PowerShell Get-Registry, Get-Project, Get-WorkersRegistry, Get-Worker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .atomic import read_json

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]+$")

VALID_TRANSPORTS = ("local", "ssh", "ssh-shell", "remote-worktree", "agent")
VALID_RUN_MODES = ("auto", "manual", "sandbox")
VALID_ROLES = ("architect", "implement", "review", "test")


def assert_safe_id(value: str, label: str = "ID") -> None:
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"{label} allows only letters, digits, dot, underscore, hyphen: {value}")


def assert_safe_session_id(value: str) -> None:
    if not value or not _SAFE_SESSION_RE.match(value):
        raise ValueError(f"sessionId allows only letters, digits, underscore, hyphen: {value}")


@dataclass
class ProjectConfig:
    id: str
    transport: str
    project_root: str
    run_mode: str = "auto"
    model: str = "huaweicloud-maas/GLM-5.2"
    timeout_minutes: int = 60
    ssh_host: str | None = None
    remote_bridge_root: str | None = None
    remote_workspace_root: str | None = None
    remote_cli_path: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectConfig":
        return cls(
            id=d["id"],
            transport=d.get("transport", "local"),
            project_root=d.get("projectRoot", ""),
            run_mode=d.get("runMode", "auto"),
            model=d.get("model", "huaweicloud-maas/GLM-5.2"),
            timeout_minutes=d.get("timeoutMinutes", 60),
            ssh_host=d.get("sshHost"),
            remote_bridge_root=d.get("remoteBridgeRoot"),
            remote_workspace_root=d.get("remoteWorkspaceRoot"),
            remote_cli_path=d.get("remoteCliPath"),
        )


@dataclass
class WorkerConfig:
    id: str
    transport: str
    host: str | None = None
    cli_path: str | None = None
    model: str = "huaweicloud-maas/GLM-5.2"
    concurrency_limit: int = 1
    enabled: bool = True
    capabilities: list[str] = field(default_factory=list)
    endpoint: str | None = None
    agent_token_env: str | None = None
    agent_token: str | None = None

    def __repr__(self) -> str:
        return (
            f"WorkerConfig(id={self.id!r}, endpoint={self.endpoint!r}, "
            f"enabled={self.enabled!r})"
        )

    @classmethod
    def from_dict(cls, d: dict) -> "WorkerConfig":
        endpoint = d.get("endpoint")
        return cls(
            id=d["id"],
            transport=d.get("transport", "agent" if endpoint else "ssh"),
            host=d.get("host"),
            cli_path=d.get("cliPath"),
            model=d.get("model", "huaweicloud-maas/GLM-5.2"),
            concurrency_limit=d.get("concurrencyLimit", 1),
            enabled=d.get("enabled", True),
            capabilities=d.get("capabilities", ["implement", "review", "test"]),
            endpoint=endpoint,
            agent_token_env=d.get("agentTokenEnv"),
            agent_token=d.get("agentToken"),
        )


@dataclass
class Registry:
    schema_version: int
    defaults: dict
    projects: list[ProjectConfig]

    @classmethod
    def from_dict(cls, d: dict) -> "Registry":
        defaults = d.get("defaults", {})
        return cls(
            schema_version=d.get("schemaVersion", 1),
            defaults=defaults,
            projects=[
                ProjectConfig.from_dict({**defaults, **p})
                for p in d.get("projects", [])
            ],
        )


@dataclass
class WorkersRegistry:
    schema_version: int
    defaults: dict
    workers: list[WorkerConfig]

    @classmethod
    def from_dict(cls, d: dict) -> "WorkersRegistry":
        defaults = d.get("defaults", {})
        return cls(
            schema_version=d.get("schemaVersion", 1),
            defaults=defaults,
            workers=[
                WorkerConfig.from_dict({**defaults, **w})
                for w in d.get("workers", [])
            ],
        )


def load_registry(registry_path: str | Path) -> Registry:
    return Registry.from_dict(read_json(registry_path))


def load_workers_registry(workers_path: str | Path) -> WorkersRegistry:
    return WorkersRegistry.from_dict(read_json(workers_path))


def get_project(registry: Registry, project_id: str) -> ProjectConfig:
    matches = [p for p in registry.projects if p.id == project_id]
    if len(matches) != 1:
        raise ValueError(f"Project not registered or duplicate: {project_id}")
    return matches[0]


def get_worker(workers_registry: WorkersRegistry, worker_id: str) -> WorkerConfig:
    matches = [w for w in workers_registry.workers if w.id == worker_id]
    if len(matches) != 1:
        raise ValueError(f"Worker not registered or duplicate: {worker_id}")
    return matches[0]