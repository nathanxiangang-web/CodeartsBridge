# AI生成
"""Bridge core domain layer.

Exports all domain models, state machine, events, and errors.
"""

from __future__ import annotations

from .models import (
    AgentConfig, RuntimeConfig, WorkspaceConfig,
    Project, Worker, Task, TaskExecution, TaskReview,
    Assignment, Lease, ExecutionPlan, ResolvedExecutionConfig,
    Registry, WorkersRegistry, load_registry, load_workers_registry,
    ROLES, COMMON_SKILLS, TRANSPORT_TYPES, WORKSPACE_TYPES, AGENT_TYPES,
)
from .state import (
    CREATED, READY, QUEUED, STARTING, RUNNING, VERIFYING,
    REVIEW_REQUIRED, APPROVED, INTEGRATING, INTEGRATED, DONE,
    ASSISTANCE_REQUIRED, RETRYABLE, AUTH_REQUIRED, CANCELLED,
    FAILED, FIX_REQUIRED, CONFLICT, STALE, BLOCKED,
    CANDIDATE_STATES, ACTIVE_STATES, TERMINAL_STATES,
    ALL_STATES, is_valid_transition, is_candidate, is_active, is_terminal,
    get_state, set_state,
)
from .events import (
    Event, EventStore,
    TASK_CREATED, TASK_STATE_CHANGED,
    ASSIGNMENT_CREATED, ASSIGNMENT_STARTED, ASSIGNMENT_FINISHED,
    WORKER_ONLINE, WORKER_OFFLINE,
    RUNTIME_HEARTBEAT, RUNTIME_TIMEOUT, RUNTIME_CANCELLED,
    REVIEW_REQUIRED as REVIEW_REQUIRED_EVENT,
    REVIEW_COMPLETED, INTEGRATION_STARTED, INTEGRATION_COMPLETED,
    POLICY_FAILED,
)
from .errors import (
    BridgeError, ConfigError, StateTransitionError,
    TaskNotFoundError, WorkerUnavailableError, LeaseExpiredError,
    TimeoutError, PolicyViolationError, IntegrationError,
)
from .ids import (
    generate_assignment_id, generate_lease_id,
    generate_event_id, generate_session_id,
)
