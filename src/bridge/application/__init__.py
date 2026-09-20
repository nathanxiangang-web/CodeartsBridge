# AI生成
"""Application layer for CodeartsBridge.

High-level service classes that orchestrate core/scheduler/runtime/agents/
workspace/policy modules. The CLI and daemon call these services,
never reaching into lower layers directly.
"""

from .task_service import create_task, get_task_status, cancel_task, list_tasks
from .dispatch_service import dispatch_tasks, DispatchResult
from .review_service import review_pass, review_fix, check_review_independence
from .projects import list_projects, get_project, register_project, unregister_project
from .workers import list_workers, get_worker, register_worker, update_worker_status, get_available_workers
from .queries import get_dashboard_summary, get_recent_events, get_task_assignments, get_worker_assignments
from .assignments import list_assignments, get_assignment, save_assignment, get_active_assignments_for_worker

__all__ = [
    "create_task", "get_task_status", "cancel_task", "list_tasks",
    "dispatch_tasks", "DispatchResult",
    "review_pass", "review_fix", "check_review_independence",
    "list_projects", "get_project", "register_project", "unregister_project",
    "list_workers", "get_worker", "register_worker", "update_worker_status", "get_available_workers",
    "get_dashboard_summary", "get_recent_events", "get_task_assignments", "get_worker_assignments",
]
