# AI生成
"""Integration service: merge approved task work into the main branch.

Application-layer service that connects the review service with
the integration module and policy verification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..core.state import get_state, set_state, CREATED, APPROVED, INTEGRATED, DONE, FAILED
from ..integration import integrate_task_branch, verify_integration, IntegrationResult

logger = logging.getLogger(__name__)


@dataclass
class IntegrationServiceResult:
    task_id: str
    success: bool
    merged_sha: str = ""
    conflict_files: list[str] = None
    verification_passed: bool = False
    error: str = ""


def integrate_approved_task(
    bridge_root: Path,
    task_id: str,
    project_root: Path,
    task_branch: str,
    target_branch: str = "main",
    verify_command: list[str] | None = None,
) -> IntegrationServiceResult:
    """Integrate an approved task into the main branch.

    State transition: APPROVED → INTEGRATED → DONE (on success)
    or APPROVED → FAILED (on failure)
    """
    bridge_root = Path(bridge_root)
    task_dir = bridge_root / "tasks" / task_id
    current = get_state(task_dir).get("state", CREATED)

    if current != APPROVED:
        return IntegrationServiceResult(
            task_id=task_id, success=False,
            error=f"Cannot integrate from state {current}",
        )

    # Perform integration
    result = integrate_task_branch(
        task_id=task_id,
        project_root=project_root,
        task_branch=task_branch,
        target_branch=target_branch,
    )

    if not result.success:
        set_state(task_dir, FAILED)
        return IntegrationServiceResult(
            task_id=task_id, success=False,
            conflict_files=result.conflict_files,
            error=result.error,
        )

    # Transition to INTEGRATED
    set_state(task_dir, INTEGRATED)

    # Run verification
    verified = verify_integration(project_root, verify_command)

    if verified:
        set_state(task_dir, DONE)
    else:
        set_state(task_dir, FAILED)

    return IntegrationServiceResult(
        task_id=task_id, success=verified,
        merged_sha=result.merged_sha,
        verification_passed=verified,
        error="" if verified else "Verification failed",
    )
