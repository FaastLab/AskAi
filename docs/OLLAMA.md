# Self-hosted LLM via Ollama

Swap from OpenAI to a local / GPU-pod open-weight model with two
config changes — no code change needed.

## Why bother

- **Privacy** — chunks + queries never leave your VM.
- **Cost** — flat hardware cost, zero per-token. Pays off above ~30M
  tokens/month.
- **Offline** — works without internet (after the model is pulled).

## Hardware sweet spots

| GPU | VRAM | Best fit | Quality vs GPT-4o |
|---|---|---|---|
| RTX 3090 / 3090 Ti | 24 GB | `qwen2.5:32b` (Q4) or `deepseek-r1:32b` | ~90% |
| RTX 4090 | 24 GB | same as above, faster | ~90% |
| 2× 3090 (NVLink) or A100 40 GB | 40 GB+ | `llama3.3:70b-instruct-q4_K_M` | ~95% |
| RTX 5060 Ti / 4070 | 16 GB | `qwen2.5:14b`, `phi4` | ~80% |

## Setup on a fresh GPU pod

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull a model (~20 GB for 32B Q4)
ollama pull qwen2.5:32b

# 3. Confirm the daemon is listening
curl http://localhost:11434/api/tags
```

## Point AskAi at it

In `.env` on the AskAi VM:

```env
# Hybrid mode (LLM local, embeddings on OpenAI — cheapest unless you
# embed millions of docs):
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:32b
OLLAMA_BASE_URL=http://<gpu-pod-ip>:11434

# Or fully OpenAI-free (single-pod product mode, see below):
# EMBEDDINGS_PROVIDER=ollama
# EMBEDDINGS_MODEL=bge-m3
# EMBEDDINGS_DIM=1024
```

Restart the api container:

```bash
docker compose --profile app restart api worker
```

The /v1/config endpoint will now report `llm_model: qwen2.5:32b`.

## A/B testing GPT-4o vs Qwen 32B

Side-by-side from the chat UI: spin up two browser tabs pointed at the
same VM, flip `.env` between `LLM_PROVIDER=openai` and
`LLM_PROVIDER=ollama` + restart the api. Ask the same question in
each tab, compare answer + citations + latency.

For the fintech sales pitch:
- **GPT-4o**: best quality, $$$ per call, data leaves.
- **Qwen 2.5 32B local**: ~90% quality, $0 per call after hardware,
  data never leaves. Better fit for FCA / PRA-regulated firms.

## Single-pod product mode (zero per-token cost, fixed monthly)

Drop ALL OpenAI calls and run the entire platform on one GPU pod.
Pitch to fintech clients: *"flat £100/mo, your data never leaves
your tenant, no third-party LLM/embeddings vendor."*

```env
# .env on the AskAi VM
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:32b
SUMMARISATION_MODEL=qwen2.5:32b   # also Ollama, no API key needed
OLLAMA_BASE_URL=http://<gpu-pod>:11434

EMBEDDINGS_PROVIDER=ollama
EMBEDDINGS_MODEL=bge-m3
EMBEDDINGS_DIM=1024

RERANKER_PROVIDER=bge             # already local; set to 'none' if no GPU headroom

# Don't even need an OpenAI key:
# OPENAI_API_KEY=
```

Then on the GPU pod, pull the embedding model too:

```bash
ollama pull qwen2.5:32b      # ~20 GB Q4
ollama pull bge-m3           # ~600 MB
```

**Critical: changing `EMBEDDINGS_DIM` requires a DB migration.** The
chunks table's `embedding` column is fixed at table creation. To switch
from 1536 (OpenAI) to 1024 (bge-m3):

```bash
# 1. Edit packages/core/alembic/versions/0003_change_embedding_dim_template.py
#    Set _NEW_DIM = 1024
# 2. Run the migration (it TRUNCATEs the chunks table — embeddings would
#    be meaningless across a model swap anyway):
make migrate
# 3. Re-ingest your corpus (the pipeline is idempotent on content_hash):
make demo-corpus
```

Verify by hitting `/v1/config` — it should show your new model + dim.

## Troubleshooting

```bash
# Confirm AskAi can reach Ollama
curl ${OLLAMA_BASE_URL}/api/tags

# Tail Ollama logs (on the GPU pod)
journalctl -u ollama -f

# AskAi side
docker logs -f askai-api | grep stream_ask
```

If `stream_ask: first_token_at` is high (>5s), the model is loading
into VRAM cold; subsequent calls should be fast. If it's `Ollama
HTTP 404 — model not found`, run `ollama pull <tag>` on the pod.
