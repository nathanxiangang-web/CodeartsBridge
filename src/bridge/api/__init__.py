# AI生成
"""HTTP REST API + Event Stream + Health API for CodeartsBridge.

Phase 9: Provides unified interface for UI and MCP.
Uses only Python standard library (http.server).
"""
from .server import BridgeAPIServer, create_handler

__all__ = ["BridgeAPIServer", "create_handler"]