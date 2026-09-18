# AI生成
"""Domain models for CodeartsBridge v2.

Core principle: Role belongs to Task, Skill belongs to Worker,
Assignment belongs to Scheduler, Execution belongs to Runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- Enums / Constants ---

ROLES = frozenset({"architect", "implement", "review", "test", "integration", "ops"})

COMMON_SKILLS = frozenset({
    "python", "typescript", "java", "go", "rust",
    "backend", "frontend", "docker", "database", "linux",
    "kubernetes", "ci-cd", "security",
})

TRANSPORT_TYPES = frozenset({"local", "ssh"})
WORKSPACE_TYPES = frozenset({"existing", "shared-readonly", "local-worktree", "remote-worktree"})
AGENT_TYPES = frozenset({"codearts", "codex", "claude", "gemini", "opencode", "custom"})


# --- Agent ---

@dataclass
class AgentConfig:
    type: str = "codearts"
    model: str = "default"

    @classmethod
    def from_dict(cls, d: dict | None) -> AgentConfig:
        d = d or {}
        return cls(type=d.get("type", "codearts"), model=d.get("model", "default"))

    def to_dict(self) -> dict:
        return {"type": self.type, "model": self.model}


# --- Runtime ---

@dataclass
class RuntimeConfig:
    transport: str = "local"
    host: str | None = None
    cli_path: str | None = None

    @classmethod
    def from_dict(cls, d: dict | None) -> RuntimeConfig:
        d = d or {}
        return cls(
            transport=d.get("transport", "local"),
            host=d.get("host"),
            cli_path=d.get("cliPath"),
        )

    def to_dict(self) -> dict:
        r = {"transport": self.transport}
        if self.host:
            r["host"] = self.host
        if self.cli_path:
            r["cliPath"] = self.cli_path
        return r


# --- Workspace Config ---

@dataclass
class WorkspaceConfig:
    supported: list[str] = field(default_factory=lambda: ["existing"])

    @classmethod
    def from_dict(cls, d: dict | None) -> WorkspaceConfig:
        d = d or {}
        return cls(supported=d.get("supported", ["existing"]))

    def to_dict(self) -> dict:
        return {"supported": self.supported}


# --- Project ---

@dataclass
class Project:
    id: str
    name: str = ""
    enabled: bool = True
    transport: str = "local"
    project_root: str = ""
    run_mode: str = "auto"
    model: str = "default"
    timeout_minutes: int = 60
    default_workspace: str = "worktree"
    required_skills: list[str] = field(default_factory=list)
    policy_profile: str = "default"
    ssh_host: str | None = None
    remote_workspace_root: str | None = None
    remote_cli_path: str | None = None
    remote_bridge_root: str | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            enabled=d.get("enabled", True),
            transport=d.get("transport", "local"),
            project_root=d.get("projectRoot", ""),
            run_mode=d.get("runMode", "auto"),
            model=d.get("model", "default"),
            timeout_minutes=d.get("timeoutMinutes", 60),
            default_workspace=d.get("defaultWorkspace", "worktree"),
            required_skills=d.get("requiredSkills", []),
            policy_profile=d.get("policyProfile", "default"),
            ssh_host=d.get("sshHost"),
            remote_workspace_root=d.get("remoteWorkspaceRoot"),
            remote_cli_path=d.get("remoteCliPath"),
            remote_bridge_root=d.get("remoteBridgeRoot"),
            metadata=d.get("metadata", {}),
        )

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "transport": self.transport,
            "projectRoot": self.project_root,
            "runMode": self.run_mode,
            "model": self.model,
            "timeoutMinutes": self.timeout_minutes,
            "defaultWorkspace": self.default_workspace,
            "requiredSkills": self.required_skills,
            "policyProfile": self.policy_profile,
        }
        if self.ssh_host:
            d["sshHost"] = self.ssh_host
        if self.remote_workspace_root:
            d["remoteWorkspaceRoot"] = self.remote_workspace_root
        if self.remote_cli_path:
            d["remoteCliPath"] = self.remote_cli_path
        if self.remote_bridge_root:
            d["remoteBridgeRoot"] = self.remote_bridge_root
        if self.metadata:
            d["metadata"] = self.metadata
        return d


# --- Worker ---

@dataclass
class Worker:
    id: str
    enabled: bool = True
    transport: str = "ssh"
    host: str | None = None
    cli_path: str | None = None
    model: str = "default"
    concurrency_limit: int = 1
    roles: list[str] = field(default_factory=lambda: ["implement"])
    skills: list[str] = field(default_factory=list)
    agent: AgentConfig = field(default_factory=AgentConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    # Legacy compat
    capabilities: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Worker:
        roles = d.get("roles")
        if roles is None:
            roles = d.get("capabilities", ["implement"])
        return cls(
            id=d["id"],
            enabled=d.get("enabled", True),
            transport=d.get("transport", "ssh"),
            host=d.get("host"),
            cli_path=d.get("cliPath"),
            model=d.get("model", "default"),
            concurrency_limit=d.get("concurrencyLimit", 1),
            roles=roles,
            skills=d.get("skills", []),
            agent=AgentConfig.from_dict(d.get("agent")),
            workspace=WorkspaceConfig.from_dict(d.get("workspace")),
            capabilities=d.get("capabilities", []),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "enabled": self.enabled,
            "transport": self.transport,
            "host": self.host,
            "cliPath": self.cli_path,
            "model": self.model,
            "concurrencyLimit": self.concurrency_limit,
            "roles": self.roles,
            "skills": self.skills,
            "agent": self.agent.to_dict(),
            "workspace": self.workspace.to_dict(),
        }

    def supports_role(self, role: str) -> bool:
        return role in self.roles

    def supports_skill(self, skill: str) -> bool:
        return skill in self.skills

    def supports_all_skills(self, skills: list[str]) -> bool:
        return all(s in self.skills for s in skills)

    def supports_workspace(self, ws_type: str) -> bool:
        return ws_type in self.workspace.supported


# --- Task Execution Config ---

@dataclass
class TaskExecution:
    preferred_worker: str | None = None
    excluded_workers: list[str] = field(default_factory=list)
    workspace: str = "isolated"
    target_minutes: int = 10
    soft_timeout_minutes: int = 12
    hard_timeout_minutes: int = 15

    @classmethod
    def from_dict(cls, d: dict | None) -> TaskExecution:
        d = d or {}
        return cls(
            preferred_worker=d.get("preferredWorker"),
            excluded_workers=d.get("excludedWorkers", []),
            workspace=d.get("workspace", "isolated"),
            target_minutes=d.get("targetMinutes", 10),
            soft_timeout_minutes=d.get("softTimeoutMinutes", 12),
            hard_timeout_minutes=d.get("hardTimeoutMinutes", 15),
        )

    def to_dict(self) -> dict:
        return {
            "preferredWorker": self.preferred_worker,
            "excludedWorkers": self.excluded_workers,
            "workspace": self.workspace,
            "targetMinutes": self.target_minutes,
            "softTimeoutMinutes": self.soft_timeout_minutes,
            "hardTimeoutMinutes": self.hard_timeout_minutes,
        }


# --- Task Review Config ---

@dataclass
class TaskReview:
    required: bool = True
    independent_worker: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> TaskReview:
        d = d or {}
        return cls(
            required=d.get("required", True),
            independent_worker=d.get("independentWorker", True),
        )

    def to_dict(self) -> dict:
        return {"required": self.required, "independentWorker": self.independent_worker}


# --- Task (META v2) ---

@dataclass
class Task:
    task_id: str
    project_id: str
    worker_id: str | None = None
    title: str = ""
    role: str = "implement"
    required_skills: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    parent_task_id: str | None = None
    priority: int = 50
    execution: TaskExecution = field(default_factory=TaskExecution)
    review: TaskReview = field(default_factory=TaskReview)
    schema_version: int = 2

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        return cls(
            task_id=d.get("taskId", d.get("task_id", "")),
            project_id=d.get("projectId", d.get("project_id", "")),
            worker_id=d.get("workerId", d.get("worker_id")),
            title=d.get("title", ""),
            role=d.get("role", "implement"),
            required_skills=d.get("requiredSkills", d.get("required_skills", [])),
            depends_on=d.get("dependsOn", d.get("depends_on", [])),
            parent_task_id=d.get("parentTaskId", d.get("parent_task_id")),
            priority=d.get("priority", 50),
            execution=TaskExecution.from_dict(d.get("execution")),
            review=TaskReview.from_dict(d.get("review")),
            schema_version=d.get("schemaVersion", 2),
        )

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "taskId": self.task_id,
            "projectId": self.project_id,
            "workerId": self.worker_id,
            "title": self.title,
            "role": self.role,
            "requiredSkills": self.required_skills,
            "dependsOn": self.depends_on,
            "parentTaskId": self.parent_task_id,
            "priority": self.priority,
            "execution": self.execution.to_dict(),
            "review": self.review.to_dict(),
        }


# --- Assignment ---

@dataclass
class Assignment:
    assignment_id: str
    task_id: str
    worker_id: str
    role: str
    attempt: int = 1
    lease_id: str | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> Assignment:
        return cls(
            assignment_id=d.get("assignmentId", d.get("assignment_id", "")),
            task_id=d.get("taskId", d.get("task_id", "")),
            worker_id=d.get("workerId", d.get("worker_id", "")),
            role=d.get("role", "implement"),
            attempt=d.get("attempt", 1),
            lease_id=d.get("leaseId", d.get("lease_id")),
            created_at=d.get("createdAt", ""),
            started_at=d.get("startedAt"),
            finished_at=d.get("finishedAt"),
        )

    def to_dict(self) -> dict:
        return {
            "assignmentId": self.assignment_id,
            "taskId": self.task_id,
            "workerId": self.worker_id,
            "role": self.role,
            "attempt": self.attempt,
            "leaseId": self.lease_id,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


# --- Lease ---

@dataclass
class Lease:
    lease_id: str
    task_id: str
    worker_id: str
    expires_at: str = ""
    heartbeat_at: str = ""
    created_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Lease:
        return cls(
            lease_id=d.get("leaseId", d.get("lease_id", "")),
            task_id=d.get("taskId", d.get("task_id", "")),
            worker_id=d.get("workerId", d.get("worker_id", "")),
            expires_at=d.get("expiresAt", ""),
            heartbeat_at=d.get("heartbeatAt", ""),
            created_at=d.get("createdAt", ""),
        )

    def to_dict(self) -> dict:
        return {
            "leaseId": self.lease_id,
            "taskId": self.task_id,
            "workerId": self.worker_id,
            "expiresAt": self.expires_at,
            "heartbeatAt": self.heartbeat_at,
            "createdAt": self.created_at,
        }


# --- ExecutionPlan ---

@dataclass
class ExecutionPlan:
    assignments: list[Assignment] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    @property
    def planned_count(self) -> int:
        return len(self.assignments)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


# --- ResolvedExecutionConfig ---

@dataclass
class ResolvedExecutionConfig:
    task_id: str
    worker_id: str
    role: str
    agent: AgentConfig = field(default_factory=AgentConfig)
    transport: dict = field(default_factory=lambda: {"type": "local"})
    workspace: dict = field(default_factory=lambda: {"type": "existing"})
    timeouts: dict = field(default_factory=lambda: {"target": 600, "soft": 720, "hard": 900})

    def to_dict(self) -> dict:
        return {
            "taskId": self.task_id,
            "workerId": self.worker_id,
            "role": self.role,
            "agent": self.agent.to_dict(),
            "transport": self.transport,
            "workspace": self.workspace,
            "timeouts": self.timeouts,
        }


# --- Registry helpers ---

@dataclass
class Registry:
    defaults: dict = field(default_factory=dict)
    projects: list[Project] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Registry:
        return cls(
            defaults=d.get("defaults", {}),
            projects=[Project.from_dict(p) for p in d.get("projects", [])],
        )

    def get_project(self, project_id: str) -> Project | None:
        for p in self.projects:
            if p.id == project_id and p.enabled:
                return p
        return None


@dataclass
class WorkersRegistry:
    defaults: dict = field(default_factory=dict)
    workers: list[Worker] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> WorkersRegistry:
        return cls(
            defaults=d.get("defaults", {}),
            workers=[Worker.from_dict(w) for w in d.get("workers", [])],
        )

    def get_worker(self, worker_id: str) -> Worker | None:
        for w in self.workers:
            if w.id == worker_id and w.enabled:
                return w
        return None

    def enabled_workers(self) -> list[Worker]:
        return [w for w in self.workers if w.enabled]


def load_registry(path: Path) -> Registry:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Registry.from_dict(data)


def load_workers_registry(path: Path) -> WorkersRegistry:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return WorkersRegistry.from_dict(data)
