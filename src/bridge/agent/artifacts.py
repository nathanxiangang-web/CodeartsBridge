"""Artifact collection for completed jobs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def collect_artifacts(job_dir: Path) -> dict[str, Any]:
    artifacts = {"files": [], "outbox": [], "salvage": []}

    outbox = job_dir / "artifacts" / "outbox"
    if outbox.exists():
        for f in sorted(outbox.iterdir()):
            if f.is_file():
                artifacts["outbox"].append({
                    "name": f.name,
                    "size": f.stat().st_size,
                })

    salvage = job_dir / "artifacts" / "runtime-salvage"
    if salvage.exists():
        for f in sorted(salvage.iterdir()):
            if f.is_file():
                artifacts["salvage"].append({
                    "name": f.name,
                    "size": f.stat().st_size,
                })

    stdout = job_dir / "stdout.jsonl"
    if stdout.exists():
        artifacts["files"].append({
            "name": "stdout.jsonl",
            "size": stdout.stat().st_size,
        })

    stderr = job_dir / "stderr.log"
    if stderr.exists():
        artifacts["files"].append({
            "name": "stderr.log",
            "size": stderr.stat().st_size,
        })

    # session.log is the raw CodeArts JSONL/PTY transcript used by the
    # Bridge UI after inflight.json is cleared. Without exporting it the
    # live monitor goes blank as soon as a task completes.
    session_log = job_dir / "session.log"
    if session_log.exists():
        artifacts["files"].append({
            "name": "session.log",
            "size": session_log.stat().st_size,
        })

    return artifacts