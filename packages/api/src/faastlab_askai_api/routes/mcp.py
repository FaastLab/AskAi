"""MCP management API (owner-only) — connection settings + a tool inspector.

Makes connecting an agent (Claude Desktop / ChatGPT / Copilot) to this
deployment's MCP server easy: it returns the endpoint, the shared token, ready
copy-paste client configs, and the exact tool catalogue. The `/call` endpoint
runs a tool against the caller's own corpus so the owner can verify the tools
work *before* wiring up a chat client — i.e. an in-app MCP inspector.

Why this exists: connecting Claude by hand was fiddly. This page removes the
guesswork (endpoint + token + config in one place) and proves the tools return
real answers.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import require_scope
from faastlab_askai_askai.service import AskAiService
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.config import get_settings
from faastlab_askai_mcp.server import dispatch_tool, tool_specs
from faastlab_askai_search.filters import SearchFilters

router = APIRouter(tags=["mcp"], prefix="/mcp")

# Reused across inspector calls so we don't rebuild the ask pipeline each time.
_ask_service = AskAiService()


class McpInfo(BaseModel):
    enabled: bool  # is the HTTP transport configured (token set)?
    transport: str  # "streamable-http"
    endpoint_path: str  # "/mcp" — UI prepends its own origin for the full URL
    tenant: str  # the tenant the HTTP MCP endpoint serves (default_tenant)
    shared_token: str | None  # the bearer token to put in the client config
    tools: list[dict]  # the tool catalogue (name / description / inputSchema)


@router.get("/info", response_model=McpInfo)
async def mcp_info(principal: Principal = Depends(require_scope("owner"))) -> McpInfo:
    """Everything the UI needs to render the connect panel + tool list."""
    settings = get_settings()
    # The HTTP MCP transport is single-tenant: it serves `default_tenant`.
    tenant = settings.default_tenant
    return McpInfo(
        # The transport is live only when a shared token is configured (the
        # handler 503s otherwise) — mirror that here so the UI shows the truth.
        enabled=bool(settings.mcp_shared_token),
        transport="streamable-http",
        endpoint_path="/mcp",
        tenant=tenant,
        # Returned to the OWNER only (require_scope guards this) so they can
        # paste it into their client config — it's their own deployment token.
        shared_token=settings.mcp_shared_token,
        tools=tool_specs(tenant),
    )


class ToolCall(BaseModel):
    tool: str = Field(description="Tool name, e.g. 'ask' or 'search_documents'")
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool: str
    result: str  # the tool's text output (what an agent would receive)
    latency_ms: float


@router.post("/call", response_model=ToolResult)
async def mcp_call(
    body: ToolCall,
    principal: Principal = Depends(require_scope("owner")),
) -> ToolResult:
    """Run a tool against the caller's OWN tenant corpus — the inspector test.

    Same execution path the MCP server uses, so a green result here means the
    agent integration will work. Scoped to the owner's tenant (not the HTTP
    endpoint's default tenant) so they test their own data."""
    started = perf_counter()
    # Correlation id so this call is fully traceable on the Usage page (it stamps
    # the gateway usage row + the audit row — the same plumbing as /v1/ask).
    request_id = uuid4().hex

    if body.tool == "ask":
        # Run the ask tool via the service directly (rather than dispatch_tool)
        # so we can thread request_id through to the gateway AND capture the
        # structured outcome (answer + citations) for a rich audit row. Without
        # this the Usage feed showed a row with no request_id -> not clickable
        # and no trace detail. This mirrors the chat /v1/ask route exactly.
        question = str(body.arguments.get("question", ""))
        filters = SearchFilters(
            only_active=not body.arguments.get("include_superseded", False)
        )
        outcome = await _ask_service.ask(
            tenant_id=principal.tenant_id,
            user_id="mcp-inspector",
            question=question,
            filters=filters,
            request_id=request_id,
        )
        # Same text shape the MCP `ask` tool returns to an agent.
        citation_lines = "\n".join(
            f"- [{c.document_title}, page {c.page_number}] {c.snippet}"
            for c in outcome.citations
        )
        text = f"{outcome.answer}\n\n## Citations\n{citation_lines}"
        # Rich, request_id-keyed audit row -> the Usage trace shows the question,
        # answer summary, and sources (the "details" + clickable URL that were
        # missing for MCP-inspector asks).
        await record_action(
            principal=principal,
            action="ask",
            resource="/v1/mcp/call",
            query=question,
            response_summary=outcome.answer[:600],
            sources=[
                {
                    "document_title": c.document_title,
                    "document_id": str(c.document_id),
                    "chunk_id": str(c.chunk_id),
                    "page_number": c.page_number,
                    "section_path": c.section_path,
                }
                for c in outcome.citations
            ],
            latency_ms=outcome.total_latency_ms,
            extra={"request_id": request_id, "tool": "ask", "via": "mcp-inspector"},
        )
        elapsed_ms = round((perf_counter() - started) * 1000.0, 1)
        return ToolResult(tool=body.tool, result=text, latency_ms=elapsed_ms)

    # Non-LLM tools (search/get/list): no gateway usage to trace, so just run
    # them through the shared dispatch path and log a light audit row.
    text = await dispatch_tool(body.tool, principal.tenant_id, body.arguments)
    elapsed_ms = round((perf_counter() - started) * 1000.0, 1)
    await record_action(
        principal=principal,
        action="mcp.inspect",
        resource="/v1/mcp/call",
        extra={"tool": body.tool, "request_id": request_id},
    )
    return ToolResult(tool=body.tool, result=text, latency_ms=elapsed_ms)
