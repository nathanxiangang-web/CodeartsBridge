# AI生成
"""Agent adapter registry.

Maps agent type strings to adapter classes. The scheduler and runtime
look up adapters by type from the registry, never importing concrete
adapters directly.
"""

from __future__ import annotations

from .base import AgentAdapter
from .codearts import CodeArtsAdapter


_REGISTRY: dict[str, type[AgentAdapter]] = {}


def register(agent_type: str, adapter_cls: type[AgentAdapter]) -> None:
    """Register an agent adapter class for a type string."""
    _REGISTRY[agent_type] = adapter_cls


def get_adapter(agent_type: str) -> AgentAdapter:
    """Get an adapter instance for the given agent type."""
    cls = _REGISTRY.get(agent_type)
    if cls is None:
        raise KeyError(f"Unknown agent type: {agent_type}")
    return cls()


def is_registered(agent_type: str) -> bool:
    """Check if an agent type is registered."""
    return agent_type in _REGISTRY


def list_types() -> list[str]:
    """List all registered agent types."""
    return list(_REGISTRY.keys())


# Register built-in adapters
register("codearts", CodeArtsAdapter)
