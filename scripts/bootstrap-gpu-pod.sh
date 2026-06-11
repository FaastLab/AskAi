#!/usr/bin/env bash
# bootstrap-gpu-pod.sh
# -----------------------------------------------------------------------------
# One-shot setup for a fresh QuickPod (or similar unprivileged GPU container)
# to run the AskAi API on GPU + expose it via Cloudflare Quick Tunnel.
#
# WHAT YOU NEED ON THE POD BEFORE RUNNING:
#   1. A tarball at /workspace/askai-pod-backup.tar.gz containing:
#        - .env          (your secrets — OpenAI key, JWT secret, etc.)
#        - askai.sql.gz  (the Postgres dump from your previous pod / VM)
#   2. The AskAi source code at /workspace/AskAi/
#      (scp from your laptop: tar -czf askai.tar.gz . --exclude=.git --exclude=.venv)
#
# USAGE:
#   chmod +x bootstrap-gpu-pod.sh
#   ./bootstrap-gpu-pod.sh
#
# WHAT IT DOES:
#   1. Installs Postgres 14 + pgvector, Redis, Python 3.12 (via uv), build deps
#   2. Restores .env and database snapshot from the backup tarball
#   3. Creates Python venv, installs torch+CUDA wheels, installs AskAi packages
#   4. Verifies GPU is visible to PyTorch
#   5. Starts uvicorn (API) + cloudflared (public HTTPS tunnel) in background
#   6. Prints the trycloudflare.com URL you point your nginx at
#
# After the script finishes, point your main VM's NPM proxy at the printed URL
# (Advanced custom config for /v1/ask, /v1/sessions, /v1/search).
# -----------------------------------------------------------------------------

set -euo pipefail

WORKSPACE="${WORKSPACE:-/workspace}"
ASKAI_DIR="$WORKSPACE/AskAi"
BACKUP="$WORKSPACE/askai-pod-backup.tar.gz"

echo "=== 1/8  Sanity checks"
[ -d "$ASKAI_DIR" ] || { echo "FATAL: $ASKAI_DIR not found — scp the source code first"; exit 1; }
[ -f "$BACKUP" ] || { echo "FATAL: $BACKUP not found — scp your previous backup first"; exit 1; }
command -v nvidia-smi >/dev/null || { echo "FATAL: no GPU in this pod"; exit 1; }
nvidia-smi --query-gpu=name,memory.total --format=csv

echo "=== 2/8  System packages (postgres 14 + pgvector, redis, python, build deps)"
echo "deb https://apt.postgresql.org/pub/repos/apt jammy-pgdg main" > /etc/apt/sources.list.d/pgdg.list
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/pgdg.gpg
apt-get update
apt-get install -y --no-install-recommends \
  git curl ca-certificates build-essential libpq-dev sudo \
  postgresql-14 postgresql-contrib-14 postgresql-14-pgvector \
  redis-server iputils-ping
service postgresql start
service redis-server start

echo "=== 3/8  Install uv (Python package manager)"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

echo "=== 4/8  Restore .env + Postgres dump from backup"
mkdir -p /tmp/restore && cd /tmp/restore
tar -xzf "$BACKUP"
cp .env "$ASKAI_DIR/.env"
# Patch DATABASE_URL and REDIS_URL to point at local services
sed -i 's|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://askai:askai@localhost:5432/askai|' "$ASKAI_DIR/.env"
sed -i 's|^REDIS_URL=.*|REDIS_URL=redis://localhost:6379/0|' "$ASKAI_DIR/.env"

sudo -u postgres psql -c "DROP DATABASE IF EXISTS askai;"
sudo -u postgres psql -c "DROP USER IF EXISTS askai;"
sudo -u postgres psql -c "CREATE USER askai WITH PASSWORD 'askai' SUPERUSER;"
sudo -u postgres createdb -O askai askai
sudo -u postgres psql -d askai -c "CREATE EXTENSION IF NOT EXISTS vector;"
gunzip -kf askai.sql.gz
sudo -u postgres psql -d askai -f /tmp/restore/askai.sql 2>&1 | tail -5

echo "=== 5/8  Create Python 3.12 venv + install packages with GPU torch"
cd "$ASKAI_DIR"
rm -rf .venv
uv venv --python 3.12
# shellcheck disable=SC1091
source .venv/bin/activate
uv pip install torch --index-url https://download.pytorch.org/whl/cu128
uv pip install \
  -e packages/core \
  -e 'packages/search[bge-reranker]' \
  -e packages/indexing \
  -e packages/summarisation \
  -e packages/askai \
  -e packages/api \
  -e packages/mcp \
  -e packages/validators \
  alembic

echo "=== 6/8  Verify GPU is visible to PyTorch"
python -c "import torch; assert torch.cuda.is_available(), 'CUDA NOT VISIBLE'; print('GPU OK:', torch.cuda.get_device_name(0))"

echo "=== 7/8  Start uvicorn API (background, logs to /tmp/api.log)"
pkill -f "uvicorn faastlab_askai_api.main:app" 2>/dev/null || true
nohup uvicorn faastlab_askai_api.main:app --host 0.0.0.0 --port 8000 > /tmp/api.log 2>&1 &
sleep 8
curl -s http://localhost:8000/healthz && echo

echo "=== 8/8  Install + start cloudflared tunnel (background, URL in /tmp/cf.log)"
if ! command -v cloudflared >/dev/null; then
  curl -L -o /tmp/cf.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  dpkg -i /tmp/cf.deb
fi
pkill -f "cloudflared tunnel" 2>/dev/null || true
nohup cloudflared tunnel --url http://localhost:8000 > /tmp/cf.log 2>&1 &
sleep 8

echo ""
echo "=============================================================="
echo "  ✅  AskAi GPU pod is live."
echo ""
echo "  GPU:        $(nvidia-smi --query-gpu=name --format=csv,noheader)"
echo "  API:        http://localhost:8000  (also bound on 0.0.0.0:8000)"
echo "  Public URL: $(grep -o 'https://[a-z-]*\.trycloudflare\.com' /tmp/cf.log | head -1)"
echo ""
echo "  Next step on your main VM:"
echo "  Edit the NPM proxy host for askai.faastlab.ai → Advanced tab,"
echo "  point /v1/(ask|sessions|search) at the Public URL above."
echo "=============================================================="
