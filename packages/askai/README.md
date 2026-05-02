# `faastlab-askai-askai`

Phase 5 — implemented (single-shot RAG; LangGraph multi-step is Phase 5.x).

## What lives here

```
src/faastlab_askai_askai/
├── adapters/
│   └── llm_openai.py            # LLMAdapter for OpenAI / Azure OpenAI (chat + stream)
├── prompts/
│   └── rag.py                   # System prompt + numbered-context user prompt
├── chains/
│   └── rag.py                   # RagChain.answer() / .stream_answer()
├── citations.py                 # Map [N] markers in answer → Citation objects
├── memory.py                    # SessionMemory backed by chat_sessions table
├── service.py                   # AskAiService — public entry (.ask + .stream_ask)
└── cli.py                       # `python -m faastlab_askai_askai.cli`
```

## Asking a question

```bash
# Streamed (default) — tokens print as the model produces them
make ask TENANT=demo-public QUERY="What does the PRA expect from firms after EU withdrawal?"

# Non-streaming
uv run python -m faastlab_askai_askai.cli \
  --tenant demo-public \
  --query "Capital requirements for UK banks?" \
  --no-stream

# Continue an existing chat session
make ask TENANT=demo-public SESSION=<uuid> QUERY="And what about Tier 2?"

# Include superseded documents
make ask TENANT=demo-public INCLUDE_SUPERSEDED=1 QUERY="Pre-2020 EU withdrawal expectations"
```

## How the answer is built

1. **Retrieve** — `SearchService.search()` (hybrid + reranker) → ranked
   chunks for this tenant, filtered by `is_active` etc.
2. **Prompt** — `build_rag_messages()` numbers the chunks `[1]…[N]`
   and packs them into a single user turn under a strict system prompt
   ("answer ONLY using the context, cite by number").
3. **LLM** — `LLMAdapter.complete` (or `.stream` for SSE) generates the
   answer. Default is `gpt-4o` with `temperature=0`.
4. **Citations** — `extract_citations()` parses `[N]` markers in the
   response and emits one `Citation` per unique source.
5. **Memory** — turn is appended to `chat_sessions.history` (capped).

## Refusals

If retrieval returns zero chunks (e.g. wrong tenant, all docs filtered
out), the chain short-circuits with a polite refusal — no LLM call,
no hallucination.

## Streaming protocol

`stream_ask()` yields three event shapes:

```json
{"event": "retrieve", "confidence": 0.42, "chunks": 7}
{"event": "token",    "text": "Firms must…"}
{"event": "done",     "session_id": "…", "citations": [...]}
```

The Phase 6 FastAPI endpoint will translate these into SSE frames.
