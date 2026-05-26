"""Streamable HTTP transport for the AskAi MCP server.

This is the "agents over a URL" surface — a hosted alternative to the
existing stdio transport in `server.py`. Customers configure their
MCP-aware agent (Claude Desktop, VS Code Copilot, Cursor, LangGraph,
custom) with::

    {
      "mcpServers": {
        "askai": {
          "url": "https://askai.faastlab.ai/mcp",
          "headers": { "Authorization": "Bearer <MCP_SHARED_TOKEN>" }
        }
      }
    }

…and the same tools the stdio server exposes (`search_documents`,
`ask`, `get_document`, `get_summary`, `list_recent`) become callable
over HTTPS without any subprocess, SSH tunnel, or local install.

Architecture:

  * `build_server()` (from `server.py`) — reused as-is; one MCP `Server`
    instance per-process, bound to the env-configured `ASKAI_TENANT`
    (defaults to `default_tenant`). Multi-tenant per-request scoping is
    a v2 task; for v1 the deployment is "one URL per tenant".
  * `StreamableHTTPSessionManager` (mcp SDK) — wraps the `Server` and
    handles session creation, request dispatch, SSE streaming.
  * `create_mcp_handler()` — returns the bare ASGI callable (for
    mounting under FastAPI) plus the session-manager async context
    manager (for hooking into FastAPI's lifespan).

Bearer-token auth is enforced at the ASGI level — simpler and safer
than relying on the SDK's optional auth providers (which are designed
for full OAuth 2.1 flows; overkill for the shared-token model we ship
in v1).

Cost / risk note: this transport intentionally trusts a single shared
token. Suitable for closed-beta and design-partner deployments where
the customer is on the other end of an NDA. Production SaaS exposure
to the open internet wants per-tenant OAuth 2.1 + scoped tokens — that
upgrade is tracked separately.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from faastlab_askai_core.config import get_settings

from faastlab_askai_mcp.server import build_server

log = logging.getLogger(__name__)


_SEND = "send"  # short alias for ASGI dict keys (lint)


async def _send_text(send, status: int, body: str) -> None:
    """Tiny helper — emit a one-shot text/plain ASGI response."""
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": body.encode("utf-8"),
        }
    )


def create_mcp_handler():
    """Build the MCP HTTP handler.

    Returns
    -------
    (handler, lifespan_cm)
        `handler` is an ASGI3 callable — mount it on your FastAPI app
        via `app.mount("/mcp", handler)`.
        `lifespan_cm` is an async context manager — wrap it around
        your FastAPI lifespan so the session manager's background
        tasks start/stop with the process.

    The handler enforces `Authorization: Bearer <MCP_SHARED_TOKEN>` on
    every request. If `mcp_shared_token` is unset in settings, every
    request returns 503 (endpoint disabled) — so an accidental deploy
    without the env var can't silently expose the corpus.
    """
    settings = get_settings()
    expected_token = settings.mcp_shared_token

    # Build the MCP server (shared across all sessions in this
    # process). The Server instance is tenant-bound via ASKAI_TENANT;
    # for multi-tenant, run multiple API processes / containers, one
    # per tenant, each with its own MCP_SHARED_TOKEN.
    server = build_server()
    session_manager = StreamableHTTPSessionManager(
        app=server,
        # stateless=False keeps a session map so resumable streams and
        # tool-call follow-ups work. SSE bytes flow as the SDK decides.
        stateless=False,
    )

    if expected_token:
        log.info("MCP HTTP transport: enabled (token len=%d)", len(expected_token))
    else:
        log.warning(
            "MCP HTTP transport: DISABLED — set MCP_SHARED_TOKEN in .env to enable."
        )

    async def handler(scope, receive, send) -> None:
        # Only HTTP — reject websockets / lifespans at this layer
        # (lifespan is owned by the parent FastAPI app).
        if scope["type"] != "http":
            return

        if not expected_token:
            await _send_text(
                send,
                503,
                "MCP HTTP endpoint disabled: MCP_SHARED_TOKEN is not configured.",
            )
            return

        # Constant-time-ish bearer check. ASGI headers are list[(bytes, bytes)].
        auth_value = b""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth_value = value
                break
        expected_header = f"Bearer {expected_token}".encode("latin-1")
        if auth_value != expected_header:
            # Mild audit trail — we log the path but never the token.
            log.warning(
                "MCP HTTP: unauthorized request to %s from %s",
                scope.get("path"),
                scope.get("client"),
            )
            await _send_text(send, 401, "Unauthorized")
            return

        # Hand off to the MCP SDK's streamable_http session manager.
        await session_manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan_cm() -> AsyncIterator[None]:
        """Async context manager wrapping the session manager.

        FastAPI's lifespan should `await stack.enter_async_context(...)`
        on this so the session manager's background workers start with
        the process and shut down cleanly on SIGTERM.
        """
        log.info("MCP HTTP: starting session manager")
        async with session_manager.run():
            yield
        log.info("MCP HTTP: session manager stopped")

    return handler, lifespan_cm
