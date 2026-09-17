# AI生成
"""Scheduler package for CodeartsBridge.

Components:
- matcher: Role and Skill matching
- dependency: Task dependency resolution
- capacity: Worker capacity planning
- affinity: Affinity and anti-affinity rules
- lease: Lease management
- planner: Main scheduling orchestration
"""

from __future__ import annotations

from .matcher import filter_candidates, score_worker, is_candidate, role_matches, skills_match
from .dependency import is_dependency_ready, get_blocked_dependencies
from .capacity import filter_with_capacity, has_capacity, available_capacity
from .affinity import apply_anti_affinity, apply_preferred, get_excluded_workers
from .lease import create_lease, renew_lease, release_lease, is_expired, get_active_lease, get_expired_leases
from .planner import select_plan, save_assignment, load_assignments
