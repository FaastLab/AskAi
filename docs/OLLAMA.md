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
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:32b
OLLAMA_BASE_URL=http://<gpu-pod-ip>:11434

# Embeddings + summarisation can stay on OpenAI (cheap), or you can
# also run an embedding model locally:
# EMBEDDINGS_PROVIDER=ollama   # (not yet implemented — Phase 5.x)
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
