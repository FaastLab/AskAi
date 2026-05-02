# `faastlab-askai-api`

Phase 6 — implemented.

## What lives here

```
src/faastlab_askai_api/
├── main.py                   # create_app() — FastAPI factory + lifespan
├── middleware/
│   ├── principal.py          # JWT auth, dev fallback, rate-limit key
│   └── audit.py              # one audit_log row per state-changing call
└── routes/
    ├── health.py             # /healthz, /readyz, /version
    ├── tenants.py            # /v1/tenants/me
    ├── documents.py          # GET /v1/documents, /v1/documents/{id}, /summary
    ├── ingest.py             # POST /v1/ingest/upload
    ├── search.py             # POST /v1/search (hybrid + reranker)
    ├── ask.py                # POST /v1/ask (blocking + SSE streaming)
    └── sessions.py           # GET /v1/sessions[/{id}]
```

## Run

```bash
make up        # postgres + redis + minio
make migrate   # apply all migrations
make dev       # uvicorn faastlab_askai_api.main:app --reload --port 8000
```

Swagger UI is at `http://localhost:8000/docs`.

## Auth

JWT bearer by default. In `APP_ENV=dev` (default), missing
`Authorization` headers fall back to the `default_tenant` setting so
you can curl the API without minting a token. Production deployments
should run with `APP_ENV=prod`.

Mint a dev token from Python:

```python
from faastlab_askai_api.middleware.principal import mint_jwt
print(mint_jwt(user_id="alice", tenant_slug="demo-public", scopes=["*"]))
```

## Streaming

`POST /v1/ask` with `{"stream": true}` returns SSE frames:

```
event: retrieve
data: {"event":"retrieve","confidence":0.42,"chunks":7}

event: token
data: {"event":"token","text":"Firms must"}
…
event: done
data: {"event":"done","session_id":"…","citations":[…]}
```

Compatible with `EventSource` in browsers and `httpx-sse` clients.

## Rate limiting

`slowapi` bucket per tenant (or per-IP for unauthenticated dev calls).
Defaults to `API_RATE_LIMIT_PER_MIN=60`; raise via `.env`.

## Tests

```bash
uv run pytest packages/api -q
```

The smoke tests use an ASGI transport so no server is needed; the
DB-backed routes are exercised end-to-end in `tests/integration/`
(Phase 12).
