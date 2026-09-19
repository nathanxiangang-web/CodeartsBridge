"""Load supervision.json feature flags with backward-compatible defaults.

Defaults preserve the pre-migration pipeline behavior: no supervision
ticks, polling-based architect review only. Deleting supervision.json or
setting supervisionEnabled=false is a one-line rollback to old behavior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


_DEFAULT_OFFSETS = (300, 480, 660, 780, 900, 960)


@dataclass(frozen=True)
class BackgroundConfig:
    enabled: bool = False
    maxSeconds: int = 90
    reserveBeforeDeadlineSeconds: int = 30
    minimumSlackSeconds: int = 120


@dataclass(frozen=True)
class HardCollectConfig:
    graceSeconds: int = 5
    salvage: bool = True


@dataclass(frozen=True)
class SupervisionConfig:
    """Feature-flag config loaded from supervision.json.

    All flags default to the pre-migration (old) pipeline behavior so
    that a missing file or missing key is equivalent to opting out.
    """

    schemaVersion: int = 1
    enabled: bool = False
    offsetsSeconds: tuple[int, ...] = _DEFAULT_OFFSETS
    heartbeatStaleSeconds: int = 90
    noProgressThreshold: int = 2
    repeatedErrorThreshold: int = 3
    background: BackgroundConfig = field(default_factory=BackgroundConfig)
    hardCollect: HardCollectConfig = field(default_factory=HardCollectConfig)
    supervisionEnabled: bool = False
    supervisionShadowMode: bool = True
    architectEventReview: bool = False
    architectPollingReview: bool = True
    architectBackgroundEnabled: bool = False
    capacityEventsEnabled: bool = False


def load_supervision_config(path: Path | None = None) -> SupervisionConfig:
    """Load supervision.json; return old-behavior defaults if missing/invalid.

    Missing keys fall back to defaults, so partial files are safe and
    deleting the file is a one-line rollback.
    """
    if path is None:
        path = Path.cwd() / "supervision.json"
    path = Path(path)
    if not path.exists():
        return SupervisionConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SupervisionConfig()
    if not isinstance(data, dict):
        return SupervisionConfig()
    return _from_dict(data)


def _from_dict(data: dict) -> SupervisionConfig:
    bg_data = data.get("background") or {}
    hc_data = data.get("hardCollect") or {}
    offsets = data.get("offsetsSeconds")
    if not isinstance(offsets, list):
        offsets = list(_DEFAULT_OFFSETS)
    return SupervisionConfig(
        schemaVersion=int(data.get("schemaVersion", 1)),
        enabled=bool(data.get("enabled", False)),
        offsetsSeconds=tuple(int(x) for x in offsets),
        heartbeatStaleSeconds=int(data.get("heartbeatStaleSeconds", 90)),
        noProgressThreshold=int(data.get("noProgressThreshold", 2)),
        repeatedErrorThreshold=int(data.get("repeatedErrorThreshold", 3)),
        background=BackgroundConfig(
            enabled=bool(bg_data.get("enabled", False)),
            maxSeconds=int(bg_data.get("maxSeconds", 90)),
            reserveBeforeDeadlineSeconds=int(bg_data.get("reserveBeforeDeadlineSeconds", 30)),
            minimumSlackSeconds=int(bg_data.get("minimumSlackSeconds", 120)),
        ),
        hardCollect=HardCollectConfig(
            graceSeconds=int(hc_data.get("graceSeconds", 5)),
            salvage=bool(hc_data.get("salvage", True)),
        ),
        supervisionEnabled=bool(data.get("supervisionEnabled", False)),
        supervisionShadowMode=bool(data.get("supervisionShadowMode", True)),
        architectEventReview=bool(data.get("architectEventReview", False)),
        architectPollingReview=bool(data.get("architectPollingReview", True)),
        architectBackgroundEnabled=bool(data.get("architectBackgroundEnabled", False)),
        capacityEventsEnabled=bool(data.get("capacityEventsEnabled", False)),
    )
