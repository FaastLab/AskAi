# `faastlab-askai-mcp`

Phase 7 — implemented.

## What it does

Exposes AskAi over the [Model Context Protocol](https://modelcontextprotocol.io/),
so Claude Desktop, Cursor, and any LangGraph / CrewAI agent can call it
as a set of tools.

Tools exposed:

| Tool | Purpose |
|---|---|
| `search_documents` | Hybrid retrieval (vector + keyword + reranker) |
| `ask` | Full RAG: cited answer to a natural-language question |
| `get_document` | Document metadata: title, type, version, active flag |
| `get_summary` | Pre-computed summary + keyphrases |
| `list_recent` | Recently ingested documents in the tenant |

## Tenant binding

The MCP transport doesn't carry a JWT, so each server instance is bound
to **one tenant** via the `ASKAI_TENANT` env var (slug or UUID). For
multi-tenant agent deployments, run multiple stdio servers or use the
REST API with a JWT instead.

## Two transports

| Transport | When to use | Where the server runs |
|---|---|---|
| **stdio** | Desktop tools (Claude Desktop / Cursor) on a user's own laptop | The client spawns it as a subprocess |
| **Streamable HTTP** | Hosted / cloud / agents over a URL | Mounted at `/mcp` inside the AskAi API |

## Run it (stdio, development)

```bash
ASKAI_TENANT=demo-public uv run python -m faastlab_askai_mcp.server
```

## Run it (Streamable HTTP, production)

The HTTP transport is **mounted automatically by `faastlab-askai-api`**
at `/mcp` whenever `MCP_SHARED_TOKEN` is set in `.env`. No separate
process to manage — same uvicorn worker that serves `/v1/*` also
serves `/mcp`.

Enable it:

```bash
# In your .env on the host running the API:
MCP_SHARED_TOKEN=$(openssl rand -hex 32)
# Then restart:
docker compose up -d --force-recreate api
```

Smoke-test the endpoint:

```bash
curl -i https://askai.yourhost.com/mcp/   # → 401 without bearer
curl -i https://askai.yourhost.com/mcp/ -H "Authorization: Bearer $MCP_SHARED_TOKEN"   # → 200 (initialize handshake)
```

Wire it to Claude Desktop (no local install, no SSH):

```json
{
  "mcpServers": {
    "askai-finreg": {
      "url": "https://askai.yourhost.com/mcp",
      "headers": { "Authorization": "Bearer <MCP_SHARED_TOKEN>" }
    }
  }
}
```

The tools (`search_documents`, `ask`, …) are identical between the
stdio and HTTP transports — only the pipe changes.

**Auth model.** v1 ships single-shared-token auth — suitable for
closed-beta and design-partner deployments where the customer is on
the other end of an NDA. For multi-tenant production SaaS, plan to
upgrade to per-tenant OAuth 2.1 with scoped access tokens.

## Wire to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or the equivalent on Windows / Linux:

```json
{
  "mcpServers": {
    "askai-finreg": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/AskAi",
        "run", "python", "-m", "faastlab_askai_mcp.server"
      ],
      "env": {
        "ASKAI_TENANT": "demo-public",
        "OPENAI_API_KEY": "sk-…"
      }
    }
  }
}
```

Restart Claude Desktop. AskAi appears as a tool source — ask
"summarise the PRA's stance on EU exit" and Claude will call
`ask` with the appropriate question.

## Wire to Cursor

Same shape, in Cursor's MCP configuration UI.

## Wire to a custom LangGraph agent

```python
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(
    command="uv",
    args=["run", "python", "-m", "faastlab_askai_mcp.server"],
    env={"ASKAI_TENANT": "demo-public"},
)
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        # Convert MCP tools → LangGraph tools, then build the agent.
```
