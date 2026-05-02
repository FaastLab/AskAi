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

## Run it

Stdio (development):

```bash
ASKAI_TENANT=demo-public uv run python -m faastlab_askai_mcp.server
```

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
