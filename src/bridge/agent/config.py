"""Agent configuration — allowed project roots and capacity."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AgentConfig:
    def __init__(self, config_path: str | Path | None = None):
        self.allowed_roots: list[str] = []
        self.capacity: int = 1
        self.agent_version: str = "0.1.0"
        self.hostname: str = ""

        if config_path:
            self.load(config_path)

    def load(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.allowed_roots = data.get("allowedRoots", [])
        self.capacity = data.get("capacity", 1)
        self.agent_version = data.get("agentVersion", "0.1.0")

    def is_project_allowed(self, project_root: str) -> bool:
        if not self.allowed_roots:
            return True
        resolved = str(Path(project_root).resolve())
        for allowed in self.allowed_roots:
            if resolved == str(Path(allowed).resolve()):
                return True
            if resolved.startswith(str(Path(allowed).resolve()) + "/"):
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowedRoots": self.allowed_roots,
            "capacity": self.capacity,
            "agentVersion": self.agent_version,
        }