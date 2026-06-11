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

> **Production runs in Docker Compose** (containers `askai-api`, `askai-worker`,
> `askai-web`, `askai-postgres`, image `faastlab/askai:local`). The API has **no
> published host port** — it's reached only via NPM → `askai-web` nginx → api,
> i.e. through your public domain (e.g. `https://askai.faastlab.ai`). Health
> path is **`/healthz`** (not `/health`). Use the commands below on a Docker
> host. (The dev/`make`/`uvicorn`/`localhost` variants are in §8.)

```bash
cd ~/AskAi
git checkout main && git pull        # or the merged feature branch
# Rebuild the image WITH the new code and recreate the app containers:
docker compose --profile app up -d --build api worker web

# Apply migrations INSIDE the api container (it has alembic; DB is on the
# compose network as `postgres`). The CMD is plain uvicorn — it does NOT
# auto-migrate, so this step is required after a schema change:
docker exec -w /app/packages/core askai-api alembic upgrade head
docker exec -w /app/packages/core askai-api alembic current   # -> 0007_prompts (head)

```

This applies the AI-gateway tables:
- `0006_llm_usage` — per-call token/cost/latency ledger (quotas + observability)
- `0007_prompts` — versioned prompt registry

**Safe-by-default:** quotas are inert until a tenant has a cap configured, so
the migration never throttles anyone by surprise.

> ⚠️ Common gotchas on a shared box: another container may own host port 8000
> (so `curl localhost:8000/...` hits the WRONG service); `python` may be
> `python3`; Postgres is the `askai-postgres` container (host port may be
> remapped, e.g. 5433 → 5432).

---

## 2. Verify Core is live

```bash
# Health via the public domain (api has no host port):
curl -s https://<your-domain>/healthz                    # 200 OK
# Migration head + tables (run against the containers):
docker exec -w /app/packages/core askai-api alembic current   # -> 0007_prompts (head)
docker exec -it askai-postgres psql -U askai -d askai -c "\dt llm_usage" -c "\dt prompts"
```

---

## 3. Smoke-test #4 AI Gateway

The whole point: prove **per-tenant quotas, the usage ledger, and model
routing** work end-to-end. ~3 minutes.

> Set `DOMAIN=https://<your-domain>` (e.g. `https://askai.faastlab.ai`) and use
> `python3`. All psql runs through the `askai-postgres` container.

### 3a. Get a bearer token from your EXISTING login

```bash
DOMAIN=https://askai.faastlab.ai
TOKEN=$(curl -s -X POST $DOMAIN/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"YOUR_EMAIL","password":"YOUR_PASSWORD"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "$TOKEN"
# (New account instead? Same call against /v1/auth/signup with an added
#  "organisation":"Acme Test" field; password min 8 chars.)
```

Find your tenant slug:
```bash
docker exec -it askai-postgres psql -U askai -d askai \
  -c "SELECT slug, name FROM tenants ORDER BY created_at DESC LIMIT 5;"
#  -> note your slug
```

### 3b. Set a tiny quota on that tenant

A cap is just JSON on the tenant row — no migration, no restart (replace SLUG):
```bash
docker exec -it askai-postgres psql -U askai -d askai -c \
"UPDATE tenants SET settings = coalesce(settings,'{}'::jsonb) || \
 '{\"gateway\":{\"quota\":{\"requests_per_day\":1,\"tokens_per_day\":100000}}}'::jsonb \
 WHERE slug='SLUG';"
```

### 3c. Prove the quota fires (two asks → 200 then 429)

```bash
for i in 1 2; do
  curl -s -o /dev/null -w "ask $i -> %{http_code}\n" -X POST $DOMAIN/v1/ask \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"query":"What is this system?","stream":false}'
done
#  -> ask 1 -> 200
#     ask 2 -> 429    (Retry-After + x-quota-limit-kind/limit/used headers)

# To SEE the 429 headers:
curl -s -D - -o /dev/null -X POST $DOMAIN/v1/ask \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"again","stream":false}' | grep -i "http/\|x-quota\|retry-after"
```

### 3d. Confirm the usage ledger

```bash
docker exec -it askai-postgres psql -U askai -d askai -c \
"SELECT created_at, purpose, provider, model, total_tokens, status \
 FROM llm_usage ORDER BY id DESC LIMIT 5;"
#  Expect: an 'ok' chat row (tokens > 0) AND a 'quota_denied' row for the blocked call.
```

✅ Gateway verified: quota enforced (429 + headers), denial audited, usage ledgered.

### 3e. (Optional) Routing decision is recorded

Pin this tenant's chat model and confirm the ledger reflects it (replace SLUG):
```bash
docker exec -it askai-postgres psql -U askai -d askai -c \
"UPDATE tenants SET settings = coalesce(settings,'{}'::jsonb) || \
 '{\"gateway\":{\"models\":{\"chat\":\"ollama:qwen2.5:7b\"}}}'::jsonb \
 WHERE slug='SLUG';"
# Raise the quota first so the call isn't blocked, then /v1/ask once, then:
docker exec -it askai-postgres psql -U askai -d askai -c \
"SELECT model, provider FROM llm_usage WHERE purpose='chat' ORDER BY id DESC LIMIT 1;"
#  -> model = qwen2.5:7b, provider = ollama
```
> Note: today the **ledger records** the routed model. Actual provider/model
> *dispatch* switches once the RAG chain calls `AIGateway` (the facade exists;
> chain cutover is the tracked follow-up). Until then, routing is observable but
> generation uses the configured default.

### 3f. Reset the test tenant (optional)

```bash
docker exec -it askai-postgres psql -U askai -d askai -c \
"UPDATE tenants SET settings = settings - 'gateway' WHERE slug='SLUG';"
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
#   set GATEWAY_ENABLED=false in .env, then:
docker compose --profile app restart api worker

# Roll back the gateway migrations (last resort) — inside the container:
docker exec -it askai-api sh -lc \
  "cd /app/packages/core && alembic downgrade 0005_users_trial"   # drops prompts + llm_usage
```

---

## 6. New-customer setup checklist

- [ ] GPU tier up + verified (`gpu-stack/RUNBOOK.md` §3)
- [ ] `.env` points at the sovereign endpoints; `EMBEDDINGS_DIM=1024`
- [ ] `git pull` → `docker compose --profile app up -d --build`
- [ ] `docker exec askai-api ... alembic upgrade head` → `alembic current` = head
- [ ] `/healthz` 200 via the domain; `llm_usage` + `prompts` tables exist
- [ ] Smoke-test §3 passes (200 then 429; ledger rows present)
- [ ] Set the customer's real quota (§4) or a global default
- [ ] (Self-hosted) private GHCR image built; (SaaS) tenant provisioned
- [ ] Wrapper (Legal/Academy/SME) deployed on top, pointed at Core

---

## 7. Cheat sheet (production / Docker)

```bash
DOMAIN=https://askai.faastlab.ai
git pull && docker compose --profile app up -d --build api worker web    # deploy new code
docker exec -w /app/packages/core askai-api alembic upgrade head   # migrate
docker exec -w /app/packages/core askai-api alembic current        # head check
curl -s $DOMAIN/healthz                                                   # API up (note: /healthz)
docker exec -it askai-postgres psql -U askai -d askai                     # DB shell
#   quota:  UPDATE tenants SET settings = ... WHERE slug='...';
#   ledger: SELECT * FROM llm_usage ORDER BY id DESC LIMIT 5;
```

---

## 8. Dev / local (NOT production)

For a laptop checkout without Docker app containers:
```bash
make up && make migrate                                  # infra + schema (host uv)
uv run uvicorn faastlab_askai_api.main:app --port 8000   # serve on localhost:8000
make test                                                # full test suite
```
Health here is also `/healthz`. This path assumes `uv` + Python on the host.
