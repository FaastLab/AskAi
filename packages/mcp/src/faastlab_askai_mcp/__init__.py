"""MCP server exposing AskAi as tools to MCP-compatible agents."""

from faastlab_askai_mcp.server import build_server, run_stdio

__all__ = ["build_server", "run_stdio"]
__version__ = "0.1.0"
