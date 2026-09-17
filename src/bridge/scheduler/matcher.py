# AI生成
"""Role and Skill matching for scheduler."""

from __future__ import annotations

from ..core.models import Worker, Task


def role_matches(worker: Worker, role: str) -> bool:
    """Check if worker supports the given role."""
    return worker.supports_role(role)


def skills_match(worker: Worker, required_skills: list[str]) -> bool:
    """Check if worker has all required skills."""
    if not required_skills:
        return True
    return worker.supports_all_skills(required_skills)


def is_candidate(worker: Worker, task: Task) -> bool:
    """Check if worker is a candidate for this task (role + skills)."""
    if not worker.enabled:
        return False
    if not role_matches(worker, task.role):
        return False
    if not skills_match(worker, task.required_skills):
        return False
    return True


def filter_candidates(workers: list[Worker], task: Task) -> list[Worker]:
    """Filter workers that are candidates for the given task."""
    return [w for w in workers if is_candidate(w, task)]


def score_worker(worker: Worker, task: Task) -> int:
    """Score a worker for a task. Higher is better.

    Factors:
    - Preferred worker: +1000
    - Skill overlap: +10 per matching skill
    - Role exclusivity: fewer roles = more specialized = higher score
    """
    score = 0

    if task.execution.preferred_worker == worker.id:
        score += 1000

    # Skill overlap bonus
    task_skills = set(task.required_skills)
    worker_skills = set(worker.skills)
    score += len(task_skills & worker_skills) * 10

    # Specialization bonus: fewer roles means more specialized
    score += max(0, 10 - len(worker.roles))

    return score
