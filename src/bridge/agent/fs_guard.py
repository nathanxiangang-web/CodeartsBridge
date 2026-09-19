"""Filesystem guard — path traversal prevention."""
from __future__ import annotations

from pathlib import Path


class FsGuardError(Exception):
    pass


def validate_path(project_root: str | Path, relative_path: str) -> Path:
    root = Path(project_root).resolve()
    resolved = (root / relative_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise FsGuardError(f"Path escapes project root: {relative_path}")
    return resolved


def is_safe_write_path(path: Path) -> bool:
    parts = path.parts
    for part in parts:
        if part == ".ssh":
            return False
        if part in (".env", "credentials.json", "token", "secret"):
            return False
    return True