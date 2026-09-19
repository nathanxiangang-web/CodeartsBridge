"""Data models for the supervision subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field


SUPERVISION_OFFSETS_SECONDS = (300, 480, 660, 780, 900, 960)


@dataclass
class SupervisionPlan:
    task_id: str
    worker_id: str | None
    running_at: str
    next_stage: int
    next_due_at: str | None
    completed_stages: list[int]
    cancelled: bool = False
    last_event_id: str | None = None
    last_event_at: str | None = None
    last_progress_hash: str | None = None
    no_progress_count: int = 0
    repeated_error_count: int = 0
    version: int = 1


@dataclass(order=True)
class DeadlineEntry:
    due_monotonic: float
    due_wallclock: str = field(compare=False)
    task_id: str = field(compare=False)
    stage: int = field(compare=False)
    generation: int = field(compare=False)


@dataclass
class InspectionResult:
    """Result of inspecting a task at a supervision stage."""

    task_id: str
    stage: int
    alert: bool = False
    summary: str = ""
    deliverables: dict = field(default_factory=dict)
    progress_hash: str | None = None
    error_signature: str | None = None


@dataclass
class ArchitectEvent:
    """Event emitted by Supervisor for the Architect to handle."""

    task_id: str
    event_type: str
    stage: int
    summary: str
    payload: dict = field(default_factory=dict)
