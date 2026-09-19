"""Tests for BackgroundScheduler (AR-04)."""

from __future__ import annotations

import time

from bridge.supervision.background import BackgroundScheduler


def test_insufficient_slack_no_start():
    bg = BackgroundScheduler(min_slack=120)
    started = bg.try_run(lambda: None, slack_seconds=100)
    assert started is False
    assert bg.is_running() is False


def test_sufficient_slack_starts():
    bg = BackgroundScheduler(min_slack=120, reserve_seconds=10, max_seconds=30)
    flag = []
    started = bg.try_run(lambda: flag.append(1), slack_seconds=200)
    assert started is True
    bg.join(timeout=5)
    assert flag == [1]


def test_respects_max_seconds():
    bg = BackgroundScheduler(max_seconds=1, reserve_seconds=0, min_slack=0)
    started = bg.try_run(lambda: time.sleep(0.1), slack_seconds=100)
    assert started is True
    bg.join(timeout=5)
    assert bg.is_running() is False


def test_reserve_subtracted():
    bg = BackgroundScheduler(max_seconds=90, reserve_seconds=30, min_slack=0)
    started = bg.try_run(lambda: None, slack_seconds=25)
    assert started is False


def test_is_running_during_task():
    bg = BackgroundScheduler(max_seconds=30, reserve_seconds=0, min_slack=0)
    bg.try_run(lambda: time.sleep(0.2), slack_seconds=100)
    assert bg.is_running() is True
    bg.join(timeout=5)
    assert bg.is_running() is False