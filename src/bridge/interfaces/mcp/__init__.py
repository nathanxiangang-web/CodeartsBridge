# AI生成
"""MCP (Model Context Protocol) interface for CodeartsBridge.

Shares Application Services with CLI and HTTP API.
Does NOT implement a second scheduling system.
"""
from .server import MCPServer, MCPToolRegistry

__all__ = ["MCPServer", "MCPToolRegistry"]