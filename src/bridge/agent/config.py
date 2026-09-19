"""Agent configuration — capacity only. Trusted LAN, no path restrictions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AgentConfig:
    def __init__(self, config_path: str | Path | None = None):
        self.capacity: int = 1
        self.agent_version: str = "0.1.0"
        self.hostname: str = ""

        if config_path:
            self.load(config_path)

    def load(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.capacity = data.get("capacity", 1)
        self.agent_version = data.get("agentVersion", "0.1.0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capacity": self.capacity,
            "agentVersion": self.agent_version,
        }
