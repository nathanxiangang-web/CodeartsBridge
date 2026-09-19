"""Tests for ReviewLock (AR-06)."""

from __future__ import annotations

import time
from pathlib import Path

from bridge.supervision.review_lock import ReviewLock


def test_acquire_succeeds(tmp_path):
    rl = ReviewLock(tmp_path / "locks")
    assert rl.acquire("task-1") is True


def test_second_acquire_fails(tmp_path):
    rl = ReviewLock(tmp_path / "locks")
    assert rl.acquire("task-1") is True
    assert rl.acquire("task-1") is False


def test_release_allows_reacquire(tmp_path):
    rl = ReviewLock(tmp_path / "locks")
    rl.acquire("task-1")
    rl.release("task-1")
    assert rl.acquire("task-1") is True


def test_lock_ttl_expires(tmp_path):
    rl = ReviewLock(tmp_path / "locks", ttl_seconds=0)
    rl.acquire("task-1")
    time.sleep(0.01)
    assert rl.acquire("task-1") is True


def test_lock_persisted_to_disk(tmp_path):
    lock_dir = tmp_path / "locks"
    rl = ReviewLock(lock_dir)
    rl.acquire("task-1")
    assert (lock_dir / "task-1.lock").exists()
    rl2 = ReviewLock(lock_dir)
    assert rl2.is_locked("task-1") is True


def test_is_locked_after_acquire(tmp_path):
    rl = ReviewLock(tmp_path / "locks")
    rl.acquire("task-1")
    assert rl.is_locked("task-1") is True
    rl.release("task-1")
    assert rl.is_locked("task-1") is False