# Bring-your-own-key (BYOK) mode

For public live demos. When enabled, every request to `/v1/ask` and
`/v1/search` must carry the visitor's own OpenAI key — the server's
`OPENAI_API_KEY` is never used for these calls. Visitors burn their own
quota; the server pays for nothing beyond hosting + Postgres.

## How to turn it on

```env
# .env on the server
REQUIRE_BYOK=true

# (Recommended) Don't set OPENAI_API_KEY at all in BYOK-only deploys.
# OPENAI_API_KEY=
```

Restart the api container:
```bash
docker compose --profile app restart api worker
```

`/v1/config` will now report `"require_byok": true`. The Vite chat UI
detects this and pops the settings gear modal on first load.

## How visitors supply their key

The chat UI's gear icon (top-right) opens a modal — paste the key, save.
The key is stored in the browser's `localStorage` only (key:
`askai.settings.v1`) and travels with each request as the
`X-OpenAI-API-Key` header. Same pattern for an optional Cohere reranker
key (`X-Cohere-API-Key`).

For programmatic clients:

```bash
curl -X POST https://askai.example.com/v1/ask \
  -H "Content-Type: application/json" \
  -H "X-OpenAI-API-Key: sk-..." \
  -d '{"query":"…","stream":false}'
```

## How it's wired

```
┌──────────────────────┐           ┌─────────────────────────────────┐
│  Browser / curl      │           │  AskAi API (FastAPI)            │
│                      │  header   │                                 │
│  X-OpenAI-API-Key ───┼──────────▶│ BYOKMiddleware extracts header  │
│                      │           │  → contextvar (RequestSecrets)  │
│                      │           │                                 │
│                      │           │  OpenAIChatLLM._active_client() │
│                      │           │     reads contextvar            │
│                      │           │     → builds AsyncOpenAI(key=…) │
│                      │           │     for this request only       │
│                      │           │                                 │
│                      │           │  After response: contextvar     │
│                      │           │  reset → no leak across reqs    │
└──────────────────────┘           └─────────────────────────────────┘
```

Files touched:
- `packages/core/src/faastlab_askai_core/byok.py` — context-var + dataclass
- `packages/api/src/faastlab_askai_api/middleware/byok.py` — header → contextvar
- `packages/api/src/faastlab_askai_api/routes/ask.py` + `.../search.py` — 401 guard when REQUIRE_BYOK=true
- `packages/api/src/faastlab_askai_api/routes/config.py` — `/v1/config` so the UI can self-discover BYOK mode
- `packages/askai/src/faastlab_askai_askai/adapters/llm_openai.py` — per-request `_active_client()`
- `packages/indexing/src/faastlab_askai_indexing/adapters/embeddings_openai.py` — same
- `apps/web/src/lib/settings.ts` — localStorage helpers
- `apps/web/src/components/SettingsModal.tsx` — gear modal
- `apps/web/src/pages/Chat.tsx` — gear button + amber banner when BYOK required

## Hardening checklist before going truly public

- [ ] HTTPS terminated at NPM with a valid cert (BYOK keys travel as
      headers — they MUST be over TLS).
- [ ] Rate-limit per IP (slowapi already in `main.py`; bump
      `API_RATE_LIMIT_PER_MIN` to taste).
- [ ] Audit log review (`audit_log` table records every `/v1/ask`).
- [ ] Don't log the X-OpenAI-API-Key header anywhere — `audit.py`
      already stores only the path + status, not headers.
- [ ] Optional: reject keys older than X days, or scoped wrong, but
      that's OpenAI's job not ours.
