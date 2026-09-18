# AI生成
"""WorkerService — manage worker registration and status without registry loss.

Phase 8: Application Layer service for workers.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..atomic import atomic_write_json


def _load_registry(path: Path) -> tuple[dict | list, list[dict]]:
    """Load canonical or legacy worker registry while preserving its container."""
    if not path.exists():
        data = {"schemaVersion": 1, "defaults": {}, "workers": []}
        return data, data["workers"]

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        workers = data.setdefault("workers", [])
        if not isinstance(workers, list):
            raise ValueError("workers registry field must be a list")
        return data, workers
    if isinstance(data, list):
        return data, data
    raise ValueError("workers.json must contain an object or list")


def list_workers(bridge_root: str | Path) -> list[dict]:
    """List all registered workers."""
    wf = Path(bridge_root) / "workers.json"
    if not wf.exists():
        return []
    _, workers = _load_registry(wf)
    return list(workers)


def get_worker(bridge_root: str | Path, worker_id: str) -> dict | None:
    """Get a single worker by ID."""
    for w in list_workers(bridge_root):
        if w.get("id") == worker_id:
            return w
    return None


def register_worker(bridge_root: str | Path, worker: dict) -> dict:
    """Register a worker while preserving schemaVersion/defaults."""
    bridge_root = Path(bridge_root)
    wf = bridge_root / "workers.json"
    data, workers = _load_registry(wf)

    worker_id = worker.get("id")
    if worker_id and any(w.get("id") == worker_id for w in workers):
        raise ValueError(f"Worker already registered: {worker_id}")

    workers.append(worker)
    atomic_write_json(wf, data)
    return worker


def update_worker_status(bridge_root: str | Path, worker_id: str, status: str) -> dict | None:
    """Update a worker status while preserving registry metadata."""
    bridge_root = Path(bridge_root)
    wf = bridge_root / "workers.json"
    if not wf.exists():
        return None

    data, workers = _load_registry(wf)
    for w in workers:
        if w.get("id") == worker_id:
            w["status"] = status
            atomic_write_json(wf, data)
            return w
    return None


def get_available_workers(bridge_root: str | Path) -> list[dict]:
    """Get all enabled workers."""
    return [w for w in list_workers(bridge_root) if w.get("enabled", True)]
