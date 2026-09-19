# AI生成
"""E2E tests for result classifier integration (P0-09)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from bridge.result_classifier import (
    WorkerResult, classify_result,
    REVIEW_REQUIRED, BLOCKED, ASSISTANCE_REQUIRED as RC_ASSIST,
    CANCELLED as RC_CANCEL, FAILED,
)


class TestResultClassifierIntegration:
    """P0-09: verify result classifier integrates with timeout and cancel."""

    def test_cancelled_takes_priority_over_timeout(self):
        """Cancel should take priority over timeout in classifier."""
        r = WorkerResult(exit_code=1, cancelled=True, timed_out=True)
        result = classify_result(r)
        assert result.state == RC_CANCEL

    def test_assistance_from_checkpoint(self):
        """Checkpoint + assistance request -> ASSISTANCE_REQUIRED."""
        r = WorkerResult(exit_code=0, has_checkpoint=True, has_assistance_request=True)
        result = classify_result(r)
        assert result.state == RC_ASSIST

    def test_timeout_without_cancel_is_retryable(self):
        """Timeout without cancel -> RETRYABLE."""
        r = WorkerResult(exit_code=1, timed_out=True)
        result = classify_result(r)
        assert result.state == "RETRYABLE"
