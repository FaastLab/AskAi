# `faastlab-askai-core`

Shared core for AskAi. Every other package depends on this one.

## What lives here

- `adapters/` — `typing.Protocol` definitions for every external dependency
  (LLM, embeddings, vector store, storage, queue, auth). **Application code
  always depends on the Protocol, never on a concrete implementation.**
- `config/` — Pydantic `Settings`, loaded from environment.
- `db/` — SQLAlchemy 2.x async models, session factory.
- `schemas/` — Pydantic DTOs used by the API, MCP, and SDK.
- `exceptions.py` — exception hierarchy rooted at `AskAiError`.
- `factory.py` — picks adapter implementations from settings at startup.
- `alembic/` — database migrations, including pgvector extension setup,
  HNSW + GIN indexes, the `tsv` trigger, row-level security policies, and
  the seed of the three default tenants.

## What does NOT live here

- Concrete adapter implementations (those live next to the modules that
  own them — e.g. an OpenAI embedder lives in `packages/indexing/`).
- Business logic — keep this package boring on purpose.

## Phase 1 status

- [x] Adapter Protocols
- [x] Settings + factory
- [x] DB models + initial Alembic migration
- [x] Pydantic DTOs
- [x] Exception tree
- [x] Smoke tests
