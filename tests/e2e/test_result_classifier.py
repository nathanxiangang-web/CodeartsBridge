# AI生成
"""Tests for result classifier (P0-07)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.result_classifier import (
    WorkerResult, classify_result, classify_from_outbox,
    REVIEW_REQUIRED, BLOCKED, ASSISTANCE_REQUIRED, AUTH_REQUIRED,
    RETRYABLE, CANCELLED, FAILED,
)


class TestResultClassifier:
    def test_success_with_deliverables(self):
        r = WorkerResult(exit_code=0, has_result=True, has_tests=True, has_diff=True)
        result = classify_result(r)
        assert result.state == REVIEW_REQUIRED

    def test_blocker(self):
        r = WorkerResult(exit_code=0, has_blocker=True)
        result = classify_result(r)
        assert result.state == BLOCKED

    def test_assistance_request(self):
        r = WorkerResult(exit_code=0, has_checkpoint=True, has_assistance_request=True)
        result = classify_result(r)
        assert result.state == ASSISTANCE_REQUIRED

    def test_auth_error(self):
        r = WorkerResult(exit_code=1, auth_error=True)
        result = classify_result(r)
        assert result.state == AUTH_REQUIRED

    def test_quota_error_retryable(self):
        r = WorkerResult(exit_code=1, quota_error=True)
        result = classify_result(r)
        assert result.state == RETRYABLE

    def test_cancelled(self):
        r = WorkerResult(exit_code=0, cancelled=True)
        result = classify_result(r)
        assert result.state == CANCELLED

    def test_exit0_missing_deliverables(self):
        r = WorkerResult(exit_code=0, has_result=True, has_tests=False, has_diff=True)
        result = classify_result(r)
        assert result.state == FAILED
        assert "missing" in result.reason

    def test_exit_nonzero(self):
        r = WorkerResult(exit_code=1)
        result = classify_result(r)
        assert result.state == FAILED

    def test_transport_error(self):
        r = WorkerResult(exit_code=1, transport_error=True)
        result = classify_result(r)
        assert result.state == FAILED

    def test_timeout_retryable(self):
        r = WorkerResult(exit_code=1, timed_out=True)
        result = classify_result(r)
        assert result.state == RETRYABLE

    def test_cancel_takes_priority_over_auth(self):
        r = WorkerResult(exit_code=0, cancelled=True, auth_error=True)
        result = classify_result(r)
        assert result.state == CANCELLED

    def test_classify_from_outbox(self, tmp_path):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "RESULT.md").write_text("done")
        (outbox / "TESTS.md").write_text("passed")
        (outbox / "DIFF.stat").write_text("1 file")

        result = classify_from_outbox(0, outbox)
        assert result.state == REVIEW_REQUIRED

    def test_classify_from_outbox_blocker(self, tmp_path):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "BLOCKER.md").write_text("blocked")

        result = classify_from_outbox(0, outbox)
        assert result.state == BLOCKED