# AI生成
"""ID generation utilities for the bridge."""

from __future__ import annotations

import secrets
import time


def _timestamp_ms() -> int:
    return int(time.time() * 1000)


def generate_assignment_id() -> str:
    return f"asg-{_timestamp_ms()}-{secrets.token_hex(4)}"


def generate_lease_id() -> str:
    return f"lease-{_timestamp_ms()}-{secrets.token_hex(4)}"


def generate_event_id() -> str:
    return f"evt-{_timestamp_ms()}-{secrets.token_hex(6)}"


def generate_session_id(task_id: str, attempt: int) -> str:
    return f"sess-{task_id}-{attempt}-{secrets.token_hex(4)}"
