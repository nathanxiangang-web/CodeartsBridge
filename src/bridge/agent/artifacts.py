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

    return artifacts