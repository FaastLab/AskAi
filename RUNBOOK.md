# AskAi Core — Operations Runbook

Operator runbook for deploying and smoke-testing the **AskAi Core** (the shared
sovereign RAG engine). Use this when standing up Core for a **new customer**
(self-hosted box or a SaaS tenant) or after shipping a hardening change.
Everything here is copy-pasteable.

Pairs with:
- `gpu-stack/RUNBOOK.md` — the GPU inference tier (vLLM + TEI). Bring that up **first**.
- `CLAUDE.md` / `Architecture.md` — design rules.

**Bottom-up order for a full stack:** GPU tier (gpu-stack) → infra (Postgres/MinIO)
→ **Core (this doc)** → wrapper (Legal/Academy/SME).

---

## 0. Prerequisites

Before Core will serve:
1. **GPU tier up** — vLLM `:8000` + TEI `:8080` reachable over Tailscale
   (see `gpu-stack/RUNBOOK.md`, verify with its §3).
2. **Infra up** — Postgres (pgvector), Redis, MinIO. Locally: `make up`.
3. **`.env` configured** — points Core at the sovereign endpoints:
   ```
   LLM_PROVIDER=openai            # OpenAI-compatible adapter, pointed at vLLM
   LLM_BASE_URL=http://<TS_IP>:8000/v1
   LLM_MODEL=Qwen/Qwen2.5-14B-Instruct-AWQ
   EMBEDDINGS_PROVIDER=openai
   EMBEDDINGS_BASE_URL=http://<TS_IP>:8080/v1
   EMBEDDINGS_MODEL=BAAI/bge-m3
   EMBEDDINGS_DIM=1024            # bge-m3 is 1024-dim — MUST match
   OPENAI_API_KEY=sk-dummy        # ignored by the sovereign servers
   DATABASE_URL=postgresql+asyncpg://askai:askai@localhost:5432/askai
   ```

---

## 1. Deploy / upgrade Core

```bash
cd ~/AskAi            # the Core repo
make up               # infra (postgres/redis/minio) — skip if already running
make migrate          # apply ALL Alembic migrations (idempotent)
#  ^ equivalently:  cd packages/core && uv run alembic upgrade head

# Start the API (foreground dev):
uv run uvicorn faastlab_askai_api.main:app --host 0.0.0.0 --port 8000
#  or the all-in-one:  make dev   (up + migrate + API + worker)
```

`make migrate` applies the AI-gateway tables among others:
- `0006_llm_usage` — per-call token/cost/latency ledger (quotas + observability)
- `0007_prompts` — versioned prompt registry

**The gateway is safe-by-default:** quotas are inert until a tenant has a cap
configured, so this migration never throttles anyone by surprise.

---

## 2. Verify Core is live

```bash
curl -s http://localhost:8000/health                 # 200 OK
# Confirm the gateway tables exist:
docker compose exec postgres psql -U askai -d askai -c "\dt llm_usage" -c "\dt prompts"
# Confirm migration head:
cd packages/core && uv run alembic current               # -> 0007_prompts (head)
```

---

## 3. Smoke-test #4 AI Gateway

The whole point: prove **per-tenant quotas, the usage ledger, and model
routing** work end-to-end. ~3 minutes.

### 3a. Create a test tenant + token

```bash
# Signup creates a tenant (from `organisation`) and returns a bearer token.
TOKEN=$(curl -s -X POST http://localhost:8000/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@acme.dev","password":"password123","organisation":"Acme Test"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "$TOKEN"
# (Re-running? Use /v1/auth/login with the same email/password instead.)
```

Find the tenant slug (derived from the org name):
```bash
docker compose exec postgres psql -U askai -d askai \
  -c "SELECT slug, name FROM tenants ORDER BY created_at DESC LIMIT 3;"
#  -> note the slug, e.g. 'acme-test'
```

### 3b. Set a tiny quota on that tenant

A cap is just JSON on the tenant row — no migration, no restart:
```bash
docker compose exec postgres psql -U askai -d askai -c \
"UPDATE tenants SET settings = coalesce(settings,'{}'::jsonb) || \
 '{\"gateway\":{\"quota\":{\"requests_per_day\":1,\"tokens_per_day\":100000}}}'::jsonb \
 WHERE slug='acme-test';"
```

### 3c. Prove the quota fires

```bash
ASK='{"query":"What is this system?","stream":false}'

# Request 1 — allowed (consumes the 1-request budget):
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/v1/ask \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$ASK"
#  -> 200

# Request 2 — blocked by quota:
curl -s -D - -o /dev/null -X POST http://localhost:8000/v1/ask \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$ASK"
#  -> HTTP/1.1 429 Too Many Requests
#     retry-after: 3600
#     x-quota-limit-kind: requests
#     x-quota-limit: 1
#     x-quota-used: 1
```

### 3d. Confirm the usage ledger

```bash
docker compose exec postgres psql -U askai -d askai -c \
"SELECT created_at, purpose, provider, model, total_tokens, status \
 FROM llm_usage ORDER BY id DESC LIMIT 5;"
#  Expect: an 'ok' chat row (tokens > 0) AND a 'quota_denied' row for the blocked call.
```

✅ Gateway verified: quota enforced (429 + headers), denial audited, usage ledgered.

### 3e. (Optional) Routing decision is recorded

Pin this tenant's chat model and confirm the ledger reflects it:
```bash
docker compose exec postgres psql -U askai -d askai -c \
"UPDATE tenants SET settings = coalesce(settings,'{}'::jsonb) || \
 '{\"gateway\":{\"models\":{\"chat\":\"ollama:qwen2.5:7b\"}}}'::jsonb \
 WHERE slug='acme-test';"
# Raise the quota first so the call isn't blocked, then /v1/ask once, then:
docker compose exec postgres psql -U askai -d askai -c \
"SELECT model, provider FROM llm_usage WHERE purpose='chat' ORDER BY id DESC LIMIT 1;"
#  -> model = qwen2.5:7b, provider = ollama
```
> Note: today the **ledger records** the routed model. Actual provider/model
> *dispatch* switches once the RAG chain calls `AIGateway` (the facade exists;
> chain cutover is the tracked follow-up). Until then, routing is observable but
> generation uses the configured default.

### 3f. Reset the test tenant (optional)

```bash
docker compose exec postgres psql -U askai -d askai -c \
"UPDATE tenants SET settings = settings - 'gateway' WHERE slug='acme-test';"
```

---

## 4. Configure real per-customer quotas

Production caps, same mechanism (per tenant slug):
```sql
UPDATE tenants
SET settings = coalesce(settings,'{}'::jsonb) ||
 '{"gateway":{"quota":{"requests_per_day":500,"tokens_per_day":2000000}}}'::jsonb
WHERE slug = '<customer-slug>';
```
Or a **global default** for everyone via `.env` (then restart API):
```
GATEWAY_DEFAULT_REQUESTS_PER_DAY=500
GATEWAY_DEFAULT_TOKENS_PER_DAY=2000000
```
- `0` = unlimited. Tenant override beats the global default.
- Cost ledger: set `GATEWAY_PRICE_PER_1K_TOKENS` only when routing to a metered
  provider (OpenAI). Sovereign models (Qwen on our GPU) stay `0.0` — no per-token cost.

---

## 5. Disable / rollback

```bash
# Turn the gateway off entirely (quota checks become no-ops):
#   set GATEWAY_ENABLED=false in .env, restart API.

# Roll back the gateway migrations (last resort):
cd packages/core
uv run alembic downgrade 0005_users_trial     # drops prompts + llm_usage
```

---

## 6. New-customer setup checklist

- [ ] GPU tier up + verified (`gpu-stack/RUNBOOK.md` §3)
- [ ] `.env` points at the sovereign endpoints; `EMBEDDINGS_DIM=1024`
- [ ] `make up && make migrate` → `alembic current` shows head
- [ ] `/health` 200; `llm_usage` + `prompts` tables exist
- [ ] Smoke-test §3 passes (200 then 429; ledger rows present)
- [ ] Set the customer's real quota (§4) or a global default
- [ ] (Self-hosted) private GHCR image built; (SaaS) tenant provisioned
- [ ] Wrapper (Legal/Academy/SME) deployed on top, pointed at Core

---

## 7. Cheat sheet

```bash
make up && make migrate                              # infra + schema
uv run uvicorn faastlab_askai_api.main:app --port 8000   # serve
cd packages/core && uv run alembic current               # migration head
docker compose exec postgres psql -U askai -d askai      # DB shell
#   quota:  UPDATE tenants SET settings = ... WHERE slug='...';
#   ledger: SELECT * FROM llm_usage ORDER BY id DESC LIMIT 5;
make test                                            # full test suite
```
