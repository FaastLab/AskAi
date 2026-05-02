# `faastlab-askai` (SDK)

Python client for the FaastLab AskAi REST API. Both sync and async,
with SSE streaming for `ask`.

## Install

```bash
pip install faastlab-askai
# or, in this monorepo:
uv pip install -e packages/sdk
```

## Quick start

```python
from faastlab_askai_sdk import AskAiClient

client = AskAiClient(base_url="https://askai.your.host", api_key="…")

# Search
result = client.search("capital adequacy", k=5)
for hit in result.hits:
    print(f"{hit.score:.3f}  {hit.document_title}  page {hit.page_number}")

# Blocking ask
ans = client.ask("Summarise the FCA's Consumer Duty cross-cutting rules.")
print(ans.answer)
for cite in ans.citations:
    print(f"  • {cite.document_title}, page {cite.page_number}")

# Streaming ask
for event in client.stream_ask("How has SS1/19 changed since 2019?"):
    if event.get("event") == "token":
        print(event["text"], end="", flush=True)
```

## Async

```python
from faastlab_askai_sdk import AsyncAskAiClient

async with AsyncAskAiClient(base_url="…", api_key="…") as client:
    answer = await client.ask("…")
```

## Auth

`api_key` becomes a `Bearer` token; the server validates JWT
(audience/issuer match its `JWT_AUDIENCE` / `JWT_ISSUER` settings).
Use `mint_jwt()` from `faastlab_askai_api.middleware.principal` for
dev tokens.
