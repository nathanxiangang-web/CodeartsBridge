"""Feature flags for gradual rollout of supervision features (FF-01).

Wraps SupervisionConfig to provide a simple boolean flag API.  Flags
default to the pre-migration (old) pipeline behavior so that a missing
supervision.json is equivalent to opting out of all new features.
"""

from __future__ import annotations

import json
from pathlib import Path

from bridge.supervision.config import SupervisionConfig, load_supervision_config

_DEFAULTS = {
    "supervisionEnabled": False,
    "supervisionShadowMode": True,
    "architectEventReview": False,
    "architectPollingReview": True,
    "architectBackgroundEnabled": False,
    "capacityEventsEnabled": False,
}


class FeatureFlags:
    """Read and persist feature flags in supervision.json."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = Path(config_path) if config_path else Path.cwd() / "supervision.json"
        self._config: SupervisionConfig = load_supervision_config(self._path)

    def load(self) -> dict:
        """Return current flags as a dict."""
        return {
            "supervisionEnabled": self._config.supervisionEnabled,
            "supervisionShadowMode": self._config.supervisionShadowMode,
            "architectEventReview": self._config.architectEventReview,
            "architectPollingReview": self._config.architectPollingReview,
            "architectBackgroundEnabled": self._config.architectBackgroundEnabled,
            "capacityEventsEnabled": self._config.capacityEventsEnabled,
        }

    def is_enabled(self, flag: str) -> bool:
        """Check if a named flag is enabled."""
        return self.load().get(flag, _DEFAULTS.get(flag, False))

    def set_flag(self, flag: str, value: bool) -> None:
        """Persist a flag change to supervision.json."""
        data: dict = {}
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        data[flag] = bool(value)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._config = load_supervision_config(self._path)

    def rollback(self) -> None:
        """One-line rollback: disable all new features, restore old pipeline."""
        self.set_flag("supervisionEnabled", False)
        self.set_flag("architectEventReview", False)
        self.set_flag("architectPollingReview", True)