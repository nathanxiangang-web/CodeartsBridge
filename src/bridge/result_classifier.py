# AI生成
"""Canonical worker result classifier.

Pure function: maps (exit_code, outbox files, transport result) -> canonical state.
All transports (local/ssh/remote-worktree) use the same classifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Canonical states
REVIEW_REQUIRED = "REVIEW_REQUIRED"
BLOCKED = "BLOCKED"
ASSISTANCE_REQUIRED = "ASSISTANCE_REQUIRED"
AUTH_REQUIRED = "AUTH_REQUIRED"
RETRYABLE = "RETRYABLE"
CANCELLED = "CANCELLED"
FAILED = "FAILED"
DONE = "DONE"


@dataclass
class WorkerResult:
    """Input to the classifier."""
    exit_code: int = 0
    cancelled: bool = False
    timed_out: bool = False
    auth_error: bool = False
    quota_error: bool = False
    transport_error: bool = False
    outbox_path: str | Path | None = None
    has_result: bool = False
    has_tests: bool = False
    has_diff: bool = False
    has_blocker: bool = False
    has_checkpoint: bool = False
    has_assistance_request: bool = False


@dataclass
class ClassificationResult:
    """Output of the classifier."""
    state: str
    reason: str


def classify_result(result: WorkerResult) -> ClassificationResult:
    """Classify a worker result into a canonical state.

    Priority order (highest first):
    1. Cancelled
    2. Auth error
    3. Quota error (retryable)
    4. Transport/protocol failure
    5. Timeout (retryable)
    6. Blocker
    7. Assistance request
    8. Exit 0 but incomplete deliverables -> FAILED
    9. Exit 0 + complete deliverables -> REVIEW_REQUIRED
    10. Exit non-zero -> FAILED
    """
    # 1. Cancel takes priority
    if result.cancelled:
        return ClassificationResult(CANCELLED, "task cancelled by user")

    # 2. Auth error
    if result.auth_error:
        return ClassificationResult(AUTH_REQUIRED, "authorization error")

    # 3. Quota error -> retryable
    if result.quota_error:
        return ClassificationResult(RETRYABLE, "quota exceeded, retry later")

    # 4. Transport/protocol failure
    if result.transport_error:
        return ClassificationResult(FAILED, "transport/protocol failure")

    # 5. Timeout -> retryable
    if result.timed_out:
        return ClassificationResult(RETRYABLE, "timed out")

    # 6. Blocker
    if result.has_blocker:
        return ClassificationResult(BLOCKED, "BLOCKER.md found")

    # 7. Assistance request
    if result.has_checkpoint and result.has_assistance_request:
        return ClassificationResult(ASSISTANCE_REQUIRED, "checkpoint + assistance request")

    # 8. Exit 0 but incomplete deliverables -> FAILED
    if result.exit_code == 0:
        if not (result.has_result and result.has_tests and result.has_diff):
            missing = []
            if not result.has_result:
                missing.append("RESULT.md")
            if not result.has_tests:
                missing.append("TESTS.md")
            if not result.has_diff:
                missing.append("DIFF.stat")
            return ClassificationResult(FAILED, f"exit 0 but missing deliverables: {', '.join(missing)}")

        # 9. Complete deliverables -> REVIEW_REQUIRED
        return ClassificationResult(REVIEW_REQUIRED, "RESULT + TESTS + DIFF present")

    # 10. Exit non-zero -> FAILED
    return ClassificationResult(FAILED, f"exit code {result.exit_code}")


def classify_from_outbox(
    exit_code: int,
    outbox_path: str | Path,
    cancelled: bool = False,
    timed_out: bool = False,
    auth_error: bool = False,
    quota_error: bool = False,
    transport_error: bool = False,
) -> ClassificationResult:
    """Convenience: classify by reading outbox directory."""
    outbox = Path(outbox_path)

    result = WorkerResult(
        exit_code=exit_code,
        cancelled=cancelled,
        timed_out=timed_out,
        auth_error=auth_error,
        quota_error=quota_error,
        transport_error=transport_error,
        outbox_path=outbox_path,
        has_result=(outbox / "RESULT.md").is_file(),
        has_tests=(outbox / "TESTS.md").is_file(),
        has_diff=(outbox / "DIFF.stat").is_file() or (outbox / "DIFF.patch").is_file(),
        has_blocker=(outbox / "BLOCKER.md").is_file(),
        has_checkpoint=(outbox / "CHECKPOINT.md").is_file(),
        has_assistance_request=(outbox / "ASSISTANCE_REQUEST.md").is_file(),
    )

    return classify_result(result)