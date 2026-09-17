# AI生成
"""Atomic file writes - .tmp then rename, matching PowerShell Write-AtomicText/Json."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


def atomic_write_text(path: str | Path, content: str) -> None:
    """Write text atomically: create .tmp, then os.replace to target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
    tmp_path = path.parent / tmp_name
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def atomic_write_json(path: str | Path, value: object) -> None:
    """Write JSON atomically with trailing newline, matching ConvertTo-Json + NewLine."""
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text)


def read_json(path: str | Path) -> object:
    """Read a JSON file, raising FileNotFoundError if missing."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_or_none(path: str | Path) -> object | None:
    """Read JSON or return None if file doesn't exist."""
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))