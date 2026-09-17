# AI生成
"""Error types for the bridge core."""

from __future__ import annotations


class BridgeError(Exception):
    """Base error for all bridge failures."""


class ConfigError(BridgeError):
    """Configuration is invalid or missing."""


class StateTransitionError(BridgeError):
    """Invalid state transition attempted."""

    def __init__(self, from_state: str, to_state: str, reason: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        msg = f"Invalid transition: {from_state} -> {to_state}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class TaskNotFoundError(BridgeError):
    """Task does not exist."""


class WorkerUnavailableError(BridgeError):
    """No suitable worker found for assignment."""


class LeaseExpiredError(BridgeError):
    """Lease has expired and can no longer be used."""


class TimeoutError(BridgeError):
    """Operation timed out."""


class PolicyViolationError(BridgeError):
    """Policy check failed."""


class IntegrationError(BridgeError):
    """Integration (merge/conflict) failure."""
