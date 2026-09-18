# AI生成
"""Application service for canonical task integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core.state import get_state, CREATED
from ..integration import integrate_task


@dataclass
class IntegrationServiceResult:
    task_id: str
    success: bool
    new_state: str = ""
    merged_sha: str = ""
    conflict_files: list[str] = field(default_factory=list)
    verification_passed: bool = False
    error: str = ""
    dry_run: bool = False


def integrate_approved_task(
    bridge_root: Path,
    task_id: str,
    *,
    target_branch: str = "main",
    verify_command: list[str] | None = None,
    dry_run: bool = False,
) -> IntegrationServiceResult:
    """Integrate one APPROVED task through the canonical integration engine."""
    bridge_root = Path(bridge_root)
    result = integrate_task(
        task_id,
        bridge_root,
        target_branch=target_branch,
        verify_command=verify_command,
        dry_run=dry_run,
    )
    task_dir = bridge_root / "tasks" / task_id
    new_state = get_state(task_dir).get("state", CREATED) if task_dir.exists() else CREATED

    return IntegrationServiceResult(
        task_id=task_id,
        success=result.success,
        new_state=new_state,
        merged_sha=result.merged_sha,
        conflict_files=list(result.conflict_files),
        verification_passed=result.verification_passed,
        error=result.error,
        dry_run=result.dry_run,
    )
