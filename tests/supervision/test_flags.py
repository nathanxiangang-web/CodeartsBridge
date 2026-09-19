"""Tests for FeatureFlags (FF-01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.supervision.flags import FeatureFlags


def test_default_flags_backward_compatible(tmp_path):
    ff = FeatureFlags(tmp_path / "supervision.json")
    flags = ff.load()
    assert flags["supervisionEnabled"] is False
    assert flags["supervisionShadowMode"] is True
    assert flags["architectEventReview"] is False
    assert flags["architectPollingReview"] is True
    assert flags["architectBackgroundEnabled"] is False
    assert flags["capacityEventsEnabled"] is False


def test_load_from_json(tmp_path):
    path = tmp_path / "supervision.json"
    path.write_text(json.dumps({
        "supervisionEnabled": True,
        "architectEventReview": True,
        "architectPollingReview": False,
    }))
    ff = FeatureFlags(path)
    assert ff.is_enabled("supervisionEnabled") is True
    assert ff.is_enabled("architectEventReview") is True
    assert ff.is_enabled("architectPollingReview") is False


def test_set_flag_persists(tmp_path):
    path = tmp_path / "supervision.json"
    ff = FeatureFlags(path)
    ff.set_flag("supervisionEnabled", True)
    data = json.loads(path.read_text())
    assert data["supervisionEnabled"] is True
    ff2 = FeatureFlags(path)
    assert ff2.is_enabled("supervisionEnabled") is True


def test_rollback_restores_old_behavior(tmp_path):
    path = tmp_path / "supervision.json"
    ff = FeatureFlags(path)
    ff.set_flag("supervisionEnabled", True)
    ff.set_flag("architectEventReview", True)
    ff.set_flag("architectPollingReview", False)
    ff.rollback()
    ff2 = FeatureFlags(path)
    assert ff2.is_enabled("supervisionEnabled") is False
    assert ff2.is_enabled("architectEventReview") is False
    assert ff2.is_enabled("architectPollingReview") is True