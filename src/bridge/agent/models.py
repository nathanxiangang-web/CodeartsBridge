"""Data models for Bridge Worker Runtime."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class JobState(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SOFT_LIMIT = "SOFT_LIMIT"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_TIMEOUT = "COMPLETED_WITH_TIMEOUT"
    ASSISTANCE_REQUIRED = "ASSISTANCE_REQUIRED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            JobState.COMPLETED,
            JobState.COMPLETED_WITH_TIMEOUT,
            JobState.ASSISTANCE_REQUIRED,
            JobState.TIMED_OUT,
            JobState.CANCELLED,
        )


@dataclass
class JobRequest:
    taskId: str
    attempt: int = 1
    projectRoot: str = ""
    cliPath: str = "codearts"
    model: str = ""
    mode: str = "auto"
    prompt: str = ""
    softTimeoutSeconds: int = 1500
    hardTimeoutSeconds: int = 1800
    sessionId: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JobRequest":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class JobInfo:
    jobId: str
    taskId: str
    state: str = JobState.STARTING.value
    pid: int | None = None
    startedAt: float = 0.0
    lastEventAt: float = 0.0
    elapsedSeconds: int = 0
    softLimitReached: bool = False
    exitCode: int | None = None
    attempt: int = 1
    projectRoot: str = ""
    cliPath: str = "codearts"
    model: str = ""
    mode: str = "auto"
    softTimeoutSeconds: int = 1500
    hardTimeoutSeconds: int = 1800
    sessionId: str | None = None
    prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JobInfo":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def update_elapsed(self) -> None:
        if self.startedAt > 0:
            self.elapsedSeconds = int(time.time() - self.startedAt)


@dataclass
class LogEvent:
    id: str
    time: float
    type: str
    text: str = ""
    status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
