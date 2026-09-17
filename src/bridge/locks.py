# AI生成
"""File locks using fcntl.flock (Linux) or msvcrt (Windows fallback for dev)."""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path


@contextlib.contextmanager
def file_lock(lock_path: str | Path):
    """Acquire an exclusive advisory lock on a file.

    On Linux uses fcntl.flock (LOCK_EX).
    On Windows uses msvcrt.locking for dev/testing.
    The lock file is created if it doesn't exist.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def try_file_lock(lock_path: str | Path) -> bool:
    """Try to acquire a non-blocking lock. Returns True if acquired."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        os.close(fd)
        return False