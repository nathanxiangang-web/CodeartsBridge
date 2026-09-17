# AI生成
"""Timeout policy: soft and hard timeout management.

Mirrors PowerShell Bridge.TimeoutPolicy.psm1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class TimeoutPolicy:
    target_seconds: int = 600
    soft_seconds: int = 720
    hard_seconds: int = 900

    def __post_init__(self):
        if self.target_seconds <= 0:
            raise ValueError("target_seconds must be positive")
        if self.soft_seconds < self.target_seconds:
            raise ValueError("soft_seconds must be >= target_seconds")
        if self.hard_seconds < self.soft_seconds:
            raise ValueError("hard_seconds must be >= soft_seconds")

    @classmethod
    def from_minutes(
        cls,
        target_minutes: int = 10,
        soft_minutes: int = 12,
        hard_minutes: int = 15,
    ) -> "TimeoutPolicy":
        return cls(
            target_seconds=target_minutes * 60,
            soft_seconds=soft_minutes * 60,
            hard_seconds=hard_minutes * 60,
        )

    def is_soft_timeout(self, elapsed_seconds: float) -> bool:
        return elapsed_seconds >= self.soft_seconds

    def is_hard_timeout(self, elapsed_seconds: float) -> bool:
        return elapsed_seconds >= self.hard_seconds

    def is_target_met(self, elapsed_seconds: float) -> bool:
        return elapsed_seconds >= self.target_seconds

    def remaining_to_hard(self, elapsed_seconds: float) -> float:
        return max(0.0, self.hard_seconds - elapsed_seconds)

    def remaining_to_soft(self, elapsed_seconds: float) -> float:
        return max(0.0, self.soft_seconds - elapsed_seconds)