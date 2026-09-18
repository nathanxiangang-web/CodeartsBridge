# AI生成
"""Tests for bridge.utils helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from bridge.utils import format_duration


class TestFormatDuration:
    def test_subsecond(self):
        assert format_duration(0.5) == "0.5s"

    def test_seconds_only(self):
        assert format_duration(45) == "45s"

    def test_zero(self):
        assert format_duration(0) == "0s"

    def test_minutes_and_seconds(self):
        assert format_duration(90) == "1m30s"

    def test_hours_minutes_seconds(self):
        assert format_duration(3700) == "1h1m40s"

    def test_exact_minute(self):
        assert format_duration(60) == "1m0s"

    def test_exact_hour(self):
        assert format_duration(3600) == "1h0m0s"

    def test_fractional_seconds_with_minutes(self):
        assert format_duration(90.5) == "1m30.5s"

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            format_duration(-1)
