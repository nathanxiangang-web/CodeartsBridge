# AI生成
"""Agent adapter package for CodeartsBridge.

Provides a pluggable interface between the bridge core and concrete
AI coding agent CLIs (CodeArts, Claude Code, etc.).
"""

from .base import AgentAdapter, AgentRunRequest, AgentRunCommand
from .codearts import CodeArtsAdapter
from .registry import register, get_adapter, is_registered, list_types

__all__ = [
    "AgentAdapter", "AgentRunRequest", "AgentRunCommand",
    "CodeArtsAdapter",
    "register", "get_adapter", "is_registered", "list_types",
]
