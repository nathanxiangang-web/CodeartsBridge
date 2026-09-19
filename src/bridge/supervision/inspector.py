"""Concrete Inspector implementation for task supervision (SUP-03).

Inspects a running task at a supervision stage by reading its state,
heartbeat, and deliverables from disk.  Returns an InspectionResult
that the Supervisor uses to decide escalation.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from bridge.supervision.model import InspectionResult, SupervisionPlan


class TaskInspector:
    """Inspect a task at a supervision stage.

    Args:
        bridge_root: Root directory of the bridge installation.
        stale_seconds: Heartbeat staleness threshold in seconds.
    """

    def __init__(
        self,
        bridge_root: Path,
        stale_seconds: int = 90,
    ) -> None:
        self._bridge_root = Path(bridge_root)
        self._stale_seconds = stale_seconds

    def _task_dir(self, task_id: str) -> Path:
        return self._bridge_root / "tasks" / task_id

    def _read_state(self, task_id: str) -> dict | None:
        path = self._task_dir(task_id) / "state.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _read_heartbeat(self, task_id: str) -> dict | None:
        path = self._bridge_root / "runtime" / "heartbeats" / f"{task_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _compute_progress_hash(self, task_id: str) -> str | None:
        """Hash the deliverables directory to detect progress changes."""
        deliverables_dir = self._task_dir(task_id) / "deliverables"
        if not deliverables_dir.exists():
            return None
        h = hashlib.sha256()
        found = False
        for path in sorted(deliverables_dir.rglob("*")):
            if path.is_file():
                found = True
                h.update(path.name.encode())
                h.update(str(path.stat().st_size).encode())
        return h.hexdigest()[:16] if found else None

    def _detect_error(self, task_id: str) -> str | None:
        """Check for error signature in task logs."""
        log_path = self._task_dir(task_id) / "error.log"
        if not log_path.exists():
            return None
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if not content.strip():
            return None
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _is_heartbeat_stale(self, task_id: str) -> bool:
        hb = self._read_heartbeat(task_id)
        if hb is None:
            return True
        last = hb.get("timestamp", 0)
        if isinstance(last, str):
            from datetime import datetime, timezone
            try:
                dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                last = dt.timestamp()
            except ValueError:
                return True
        return (time.time() - last) > self._stale_seconds

    def inspect(
        self, task_id: str, stage: int, plan: SupervisionPlan
    ) -> InspectionResult:
        """Inspect a task and return findings for the Supervisor."""
        state = self._read_state(task_id)
        heartbeat_stale = self._is_heartbeat_stale(task_id)
        progress_hash = self._compute_progress_hash(task_id)
        error_sig = self._detect_error(task_id)

        deliverables: dict = {}
        if state is not None:
            deliverables = state.get("deliverables", {})
            if not isinstance(deliverables, dict):
                deliverables = {}

        alert = False
        summary_parts: list[str] = []

        if state is None:
            alert = True
            summary_parts.append("task state missing")
        elif state.get("status") == "FAILED":
            alert = True
            summary_parts.append("task marked FAILED")

        if heartbeat_stale:
            summary_parts.append("heartbeat stale")
            if stage >= 2:
                alert = True

        if error_sig is not None:
            summary_parts.append(f"error signature: {error_sig}")

        return InspectionResult(
            task_id=task_id,
            stage=stage,
            alert=alert,
            summary="; ".join(summary_parts) if summary_parts else "ok",
            deliverables=deliverables,
            progress_hash=progress_hash,
            error_signature=error_sig,
        )