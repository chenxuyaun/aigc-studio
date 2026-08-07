"""MCP 出口：把 AIGC Studio 能力暴露为 MCP 工具（stdio + HTTP 双模式）。"""

from app.mcp.server import mcp

__all__ = ["mcp"]
