"""MCP server — registers AskAi tools and runs over stdio.

Tools exposed (per ARCHITECTURE.md §3):
- search_documents
- get_document
- get_summary
- list_recent
- ask        (full RAG answer, blocking — agents tend to want it that way)

Tenant binding:
The MCP transport doesn't carry a JWT; instead we read `ASKAI_TENANT`
from the environment so each MCP server instance is bound to one tenant.
That matches how Claude Desktop / Cursor configure servers (one
mcp_servers entry per tenant). For multi-tenant agent deployments, run
multiple stdio servers or front them with the REST API + JWT instead.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from sqlalchemy import select

from faastlab_askai_askai.service import AskAiService
from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import Document, Tenant, get_sessionmaker
from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.service import SearchService

log = logging.getLogger(__name__)


async def _resolve_tenant_id(slug_or_id: str) -> UUID:
    try:
        return UUID(slug_or_id)
    except ValueError:
        pass
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Tenant.id).where(Tenant.slug == slug_or_id)
        )
        row = result.scalar_one_or_none()
    if row is None:
        raise RuntimeError(f"No tenant matches: {slug_or_id!r}")
    return row


# Single source of truth for the tool catalogue. Lives at module level (not
# inside build_server) so the web "MCP inspector" UI can show the exact same
# tools an agent would see — see `tool_specs()` + `dispatch_tool()` below.
def tool_specs(tenant_label: str) -> list[dict[str, Any]]:
    """The MCP tool catalogue as plain dicts (name / description / inputSchema).

    `tenant_label` is only used in the human-readable descriptions. The stdio
    server wraps these in `Tool(**spec)`; the REST inspector returns them as-is.
    """
    return [
        {
            "name": "search_documents",
            "description": (
                "Hybrid search (vector + keyword + RRF + reranker) over the "
                f"AskAi corpus for tenant '{tenant_label}'. Returns ranked chunks "
                "with scores and source provenance."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "k": {"type": "integer", "default": 8, "minimum": 1, "maximum": 50},
                    "include_superseded": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        },
        {
            "name": "ask",
            "description": (
                f"Ask AskAi a question about tenant '{tenant_label}'. Returns a "
                "cited answer (LLM-synthesised over retrieved chunks)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "include_superseded": {"type": "boolean", "default": False},
                },
                "required": ["question"],
            },
        },
        {
            "name": "get_document",
            "description": "Fetch a document's title, type, version, summary, and keyphrases.",
            "inputSchema": {
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "UUID"}},
                "required": ["document_id"],
            },
        },
        {
            "name": "get_summary",
            "description": "Return the pre-computed summary + keyphrases for a document.",
            "inputSchema": {
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "UUID"}},
                "required": ["document_id"],
            },
        },
        {
            "name": "list_recent",
            "description": "List the most recently ingested documents in this tenant.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 10, "maximum": 100}},
            },
        },
    ]


# Lazily-built singletons so dispatch_tool (used by the REST inspector) doesn't
# reconstruct services on every call. The stdio server passes its own instances.
_search_singleton: SearchService | None = None
_ask_singleton: AskAiService | None = None


async def dispatch_tool(
    name: str,
    tenant_id: UUID,
    arguments: dict[str, Any],
    *,
    search_service: SearchService | None = None,
    ask_service: AskAiService | None = None,
) -> str:
    """Run one tool for `tenant_id` and return its text result.

    The single execution path shared by the MCP stdio server (`call_tool`) and
    the REST inspector — so what the UI tests is exactly what an agent calls.
    """
    global _search_singleton, _ask_singleton
    if search_service is None:
        _search_singleton = _search_singleton or SearchService()
        search_service = _search_singleton
    if ask_service is None:
        _ask_singleton = _ask_singleton or AskAiService()
        ask_service = _ask_singleton

    if name == "search_documents":
        result = await _search_tool(search_service, tenant_id, arguments)
    elif name == "ask":
        result = await _ask_tool(ask_service, tenant_id, arguments)
    elif name == "get_document":
        result = await _doc_tool(tenant_id, arguments)
    elif name == "get_summary":
        result = await _summary_tool(tenant_id, arguments)
    elif name == "list_recent":
        result = await _list_tool(tenant_id, arguments)
    else:
        result = [TextContent(type="text", text=f"unknown tool: {name}")]
    # Tools return a list of TextContent; join into one string for callers.
    return "\n".join(c.text for c in result)


def build_server() -> Server:
    settings = get_settings()
    server: Server = Server("faastlab-askai")
    search_service = SearchService()
    ask_service = AskAiService()

    tenant_slug = os.environ.get("ASKAI_TENANT", settings.default_tenant)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        # Build the protocol Tool objects from the shared catalogue.
        return [Tool(**spec) for spec in tool_specs(tenant_slug)]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        tenant_id = await _resolve_tenant_id(tenant_slug)
        # Reuse the closure's services so the stdio server keeps warm instances.
        text = await dispatch_tool(
            name,
            tenant_id,
            arguments,
            search_service=search_service,
            ask_service=ask_service,
        )
        return [TextContent(type="text", text=text)]

    return server


# ---- Tool implementations --------------------------------------------------


async def _search_tool(service: SearchService, tenant_id: UUID, args: dict[str, Any]):
    filters = SearchFilters(only_active=not args.get("include_superseded", False))
    outcome = await service.search(
        tenant_id=tenant_id,
        query=str(args["query"]),
        k=int(args.get("k", 8)),
        filters=filters,
    )
    lines = [
        f"# Search results (confidence={outcome.confidence:.2f}, "
        f"latency={outcome.latency_ms} ms)\n"
    ]
    for hit in outcome.hits:
        flag = "" if hit.is_active else "  [SUPERSEDED]"
        lines.append(
            f"## {hit.rank}. {hit.document_title}{flag} "
            f"(page {hit.page_number}, score={hit.score:.3f})"
        )
        lines.append(hit.content[:600].strip())
        lines.append("")
    return [TextContent(type="text", text="\n".join(lines))]


async def _ask_tool(service: AskAiService, tenant_id: UUID, args: dict[str, Any]):
    filters = SearchFilters(only_active=not args.get("include_superseded", False))
    outcome = await service.ask(
        tenant_id=tenant_id,
        user_id="mcp",
        question=str(args["question"]),
        filters=filters,
    )
    citation_lines = "\n".join(
        f"- [{c.document_title}, page {c.page_number}] {c.snippet}"
        for c in outcome.citations
    )
    body = f"{outcome.answer}\n\n## Citations\n{citation_lines}"
    return [TextContent(type="text", text=body)]


async def _doc_tool(tenant_id: UUID, args: dict[str, Any]):
    doc_id = UUID(str(args["document_id"]))
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document).where(
                (Document.id == doc_id) & (Document.tenant_id == tenant_id)
            )
        )
        doc = result.scalar_one_or_none()
    if doc is None:
        return [TextContent(type="text", text="document not found")]
    body = (
        f"# {doc.title}\n"
        f"- type: {doc.doc_type or 'n/a'}\n"
        f"- version: {doc.version or 'n/a'}\n"
        f"- effective: {doc.effective_date.isoformat() if doc.effective_date else 'n/a'}\n"
        f"- active: {doc.is_active}\n"
        f"- source: {doc.source_uri}\n"
    )
    return [TextContent(type="text", text=body)]


async def _summary_tool(tenant_id: UUID, args: dict[str, Any]):
    doc_id = UUID(str(args["document_id"]))
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Document).where(
                (Document.id == doc_id) & (Document.tenant_id == tenant_id)
            )
        )
        doc = result.scalar_one_or_none()
    if doc is None:
        return [TextContent(type="text", text="document not found")]
    if not doc.summary:
        return [
            TextContent(
                type="text",
                text="summary not yet generated — run summarisation first",
            )
        ]
    keyphrases = ", ".join(doc.keyphrases or [])
    body = (
        f"# {doc.title}\n\n{doc.summary}\n\n"
        f"## Keyphrases\n{keyphrases}"
    )
    return [TextContent(type="text", text=body)]


async def _list_tool(tenant_id: UUID, args: dict[str, Any]):
    limit = int(args.get("limit", 10))
    sm = get_sessionmaker()
    async with sm() as session:
        rows = await session.execute(
            select(Document.id, Document.title, Document.doc_type, Document.is_active)
            .where(Document.tenant_id == tenant_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        records = rows.all()
    lines = [f"# Recent documents (top {limit})\n"]
    for r in records:
        flag = "" if r.is_active else "  [SUPERSEDED]"
        lines.append(f"- {r.id}  {r.title}  ({r.doc_type or 'n/a'}){flag}")
    return [TextContent(type="text", text="\n".join(lines))]


# ---- stdio entry-point -----------------------------------------------------


async def run_stdio() -> None:
    """Run the server over stdio (the transport Claude Desktop & Cursor use)."""
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
