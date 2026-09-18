# AI生成
"""WorkerService — manage worker registration and status.

Phase 8: Application Layer service for workers.
"""
from __future__ import annotations

import json
from pathlib import Path


def list_workers(bridge_root: str | Path) -> list[dict]:
    """List all registered workers."""
    wf = Path(bridge_root) / "workers.json"
    if not wf.exists():
        return []
    data = json.loads(wf.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("workers", [])
    return data


def get_worker(bridge_root: str | Path, worker_id: str) -> dict | None:
    """Get a single worker by ID."""
    for w in list_workers(bridge_root):
        if w.get("id") == worker_id:
            return w
    return None


def register_worker(bridge_root: str | Path, worker: dict) -> dict:
    """Register a new worker."""
    bridge_root = Path(bridge_root)
    wf = bridge_root / "workers.json"
    workers = list_workers(bridge_root)
    workers.append(worker)
    wf.write_text(json.dumps(workers, indent=2, ensure_ascii=False), encoding="utf-8")
    return worker


def update_worker_status(bridge_root: str | Path, worker_id: str, status: str) -> dict | None:
    """Update a worker's online/offline status."""
    bridge_root = Path(bridge_root)
    wf = bridge_root / "workers.json"
    workers = list_workers(bridge_root)
    for w in workers:
        if w.get("id") == worker_id:
            w["status"] = status
            wf.write_text(json.dumps(workers, indent=2, ensure_ascii=False), encoding="utf-8")
            return w
    return None


def get_available_workers(bridge_root: str | Path) -> list[dict]:
    """Get all enabled workers."""
    return [w for w in list_workers(bridge_root) if w.get("enabled", True)]