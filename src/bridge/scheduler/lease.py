# AI生成
"""Lease management for task execution.

Lease prevents duplicate dispatch and identifies dead workers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core.models import Lease
from ..core.ids import generate_lease_id
from ..atomic import atomic_write_json, read_json_or_none


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def create_lease(
    leases_dir: Path,
    task_id: str,
    worker_id: str,
    ttl_minutes: int = 30,
) -> Lease:
    """Create a new lease for a task-worker pair."""
    leases_dir = Path(leases_dir)
    leases_dir.mkdir(parents=True, exist_ok=True)

    now = _now()
    expires = now + timedelta(minutes=ttl_minutes)

    lease = Lease(
        lease_id=generate_lease_id(),
        task_id=task_id,
        worker_id=worker_id,
        expires_at=_iso(expires),
        heartbeat_at=_iso(now),
        created_at=_iso(now),
    )

    path = leases_dir / f"{lease.lease_id}.json"
    atomic_write_json(path, lease.to_dict())
    return lease


def renew_lease(leases_dir: Path, lease_id: str, ttl_minutes: int = 30) -> Lease | None:
    """Renew an existing lease, extending its expiry."""
    path = Path(leases_dir) / f"{lease_id}.json"
    data = read_json_or_none(path)
    if data is None:
        return None

    now = _now()
    expires = now + timedelta(minutes=ttl_minutes)
    data["expiresAt"] = _iso(expires)
    data["heartbeatAt"] = _iso(now)
    atomic_write_json(path, data)
    return Lease.from_dict(data)


def is_expired(lease: Lease) -> bool:
    """Check if a lease has expired."""
    try:
        expires = datetime.fromisoformat(lease.expires_at)
        return _now() > expires
    except (ValueError, TypeError):
        return True


def release_lease(leases_dir: Path, lease_id: str) -> bool:
    """Release a lease by removing it."""
    path = Path(leases_dir) / f"{lease_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def get_active_lease(leases_dir: Path, task_id: str) -> Lease | None:
    """Get the active (non-expired) lease for a task, if any."""
    leases_dir = Path(leases_dir)
    if not leases_dir.exists():
        return None

    for path in leases_dir.glob("*.json"):
        data = read_json_or_none(path)
        if data is None:
            continue
        lease = Lease.from_dict(data)
        if lease.task_id == task_id and not is_expired(lease):
            return lease
    return None


def get_expired_leases(leases_dir: Path) -> list[Lease]:
    """Get all expired leases for stale recovery."""
    leases_dir = Path(leases_dir)
    if not leases_dir.exists():
        return []

    expired = []
    for path in leases_dir.glob("*.json"):
        data = read_json_or_none(path)
        if data is None:
            continue
        lease = Lease.from_dict(data)
        if is_expired(lease):
            expired.append(lease)
    return expired
