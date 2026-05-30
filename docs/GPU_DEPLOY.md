# GPU stack deploy guide

Single docker-compose override that runs the full AskAi stack on a
GPU host with a sovereign LLM (Qwen via Ollama). Pairs with the
existing CPU stack on `askai.faastlab.ai` — same source code, same
schema, different image tag and `.env`.

## What this gets you

```
askai-gpu.faastlab.ai  →  api + worker on faastlab/askai:gpu
                       →  bge-reranker on GPU (~1s vs ~16s CPU)
                       →  Qwen 14B / 72B via Ollama (in-pod, no OpenAI)
                       →  bge-m3 embeddings via Ollama (optional)
                       →  same Postgres+pgvector, MinIO, Redis, web
```

CPU stack on `askai.faastlab.ai` is unchanged — keep running it for
the side-by-side latency demo (and as the OpenAI baseline).

## Host prereq (one-time per GPU box)

```bash
# 1. NVIDIA driver
nvidia-smi   # should already work on a properly-provisioned GPU host

# 2. NVIDIA Container Toolkit (so containers see the GPU)
distribution=$(. /etc/os-release; echo $ID$VERSION_ID) \
  && curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
       | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list \
       | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
       | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# 3. Verify
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

If the test command shows your GPU, you're ready.

## Bring the stack up

```bash
cd ~/AskAi
git pull                                  # latest main with these files

# Copy & edit env overrides
cp .env.gpu.example .env.gpu
$EDITOR .env.gpu                          # confirm LLM_MODEL, EMBEDDINGS_MODEL

# Build + start
docker compose \
    -f docker-compose.yml \
    -f docker-compose.gpu.yml \
    --env-file .env \
    --env-file .env.gpu \
    --profile app \
    up -d --build

# Pre-pull the models so first request is fast
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec ollama \
    ollama pull qwen2.5:14b              # ~10GB, takes a few min
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec ollama \
    ollama pull bge-m3                   # ~2GB embeddings (optional)
```

Sanity-check that PyTorch sees the GPU inside the api container:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec api \
    python -c "import torch; print('cuda=', torch.cuda.is_available(), \
                                    'device=', torch.cuda.get_device_name(0))"
```

Expected: `cuda= True device= NVIDIA <whatever-card>`.

## Corpus

Two options:

* **Quickest (recommended for benchmarks):** restore the CPU host's
  Postgres dump so both stacks see *identical* data. Keeps comparisons
  honest.
  ```bash
  # on the CPU host
  docker exec askai-postgres pg_dump -U askai -d askai --no-owner --no-acl > /tmp/askai.sql
  gzip -f /tmp/askai.sql
  scp /tmp/askai.sql.gz <gpu-host>:/tmp/

  # on the GPU host
  gunzip /tmp/askai.sql.gz
  docker exec -i askai-postgres psql -U askai -d askai < /tmp/askai.sql
  ```

* **Fresh ingest** if you also want to re-embed with bge-m3 (1024-dim
  vs OpenAI's 1536-dim). Re-run the handbook ingester after the dump
  is in place.

## NPM wiring

Add a new Proxy Host in NPM:

* Domain: `askai-gpu.faastlab.ai`
* Forward Scheme: `http`
* Forward Hostname/IP: `askai-web` (or the GPU box's hostname / private IP
  if NPM lives on a different network)
* Forward Port: `80`
* SSL: request a new Let's Encrypt cert for this hostname
* Custom Nginx config (Advanced tab) — leave **empty**. The web
  container's nginx already routes `/v1/*`, `/mcp`, `/healthz`, etc.

DO NOT add a `/mcp` block in NPM Advanced — same lesson as the CPU
host (NPM's nginx can't resolve the api container's hostname). See
`CLAUDE_SESSION2.md` §7.

## Tear down (when the benchmark / demo is over)

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml down
# Volumes (postgres-data, redis-data, minio-data, ollama-data) persist
# unless you add `-v`. Keep them if you want fast restart; nuke them
# if the pod is going away.
```

## Cost reference

Per-hour pay-as-you-go (RunPod community pricing, May 2026):

| GPU | VRAM | Sovereign Qwen fit | $/hr |
|---|---|---|---|
| RTX 3090 | 24GB | 14B Q4 + reranker | ~£0.36 |
| RTX 4090 | 24GB | 14B Q4 + reranker | ~£0.55 |
| L40S | 48GB | 32B Q4 + reranker | ~£0.68 |
| A100 80GB | 80GB | 72B Q4 + reranker + embeddings | ~£1.10 |
| H100 80GB | 80GB | 72B Q4 + reranker + embeddings | ~£2.30 |

For a single benchmark sweep (~8 runs × 15 min on A100): roughly
£3–5. Cheap.

## Related

* `scripts/bootstrap-gpu-pod.sh` — native install (no Docker) for
  unprivileged QuickPod-style hosts. Use this only if the host can't
  run Docker. Privileged pods / Azure A10 / RunPod community pods can
  all run the proper compose-based stack above.
* `tests/loadtest/` — Locust ramp + host metric collector, point
  `ASKAI_HOST` at `https://askai-gpu.faastlab.ai` for the GPU run.
* `CLAUDE_SESSION2.md` — full context from session 2, including the
  MCP + NPM topology lessons.
