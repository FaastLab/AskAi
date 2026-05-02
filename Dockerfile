# Production image — runs the FastAPI app or a Celery worker depending
# on the command (see Helm chart).
#
# Layer order is tuned for incremental rebuilds: dependency manifests
# go in first (rarely change → cached layer), then source goes in last.
# A code-only change reuses the heavy `uv sync` + apt layers.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:/root/.local/bin:${PATH}"

# System libs PyMuPDF + Unstructured + tesseract (OCR fallback) need.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpoppler-cpp-dev \
        poppler-utils \
        tesseract-ocr \
        libmagic1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -s /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

# ---- Layer 1: dependency manifests only (highly cacheable) ------------
# Bring in the workspace pyproject.toml + every package's pyproject.toml +
# the lockfile, but NO source. uv sync uses these to resolve and install
# all deps. Source-code changes don't invalidate this layer, so a
# typical rebuild after editing Python files reuses the cached venv.
COPY pyproject.toml uv.lock* ./
COPY packages/core/pyproject.toml             packages/core/pyproject.toml
COPY packages/indexing/pyproject.toml         packages/indexing/pyproject.toml
COPY packages/search/pyproject.toml           packages/search/pyproject.toml
COPY packages/summarisation/pyproject.toml    packages/summarisation/pyproject.toml
COPY packages/askai/pyproject.toml            packages/askai/pyproject.toml
COPY packages/api/pyproject.toml              packages/api/pyproject.toml
COPY packages/mcp/pyproject.toml              packages/mcp/pyproject.toml
COPY packages/sdk/pyproject.toml              packages/sdk/pyproject.toml
COPY packages/validators/pyproject.toml       packages/validators/pyproject.toml

# Stub each package's src tree so the editable install resolves.
RUN for pkg in core indexing search summarisation askai api mcp sdk validators; do \
      mkdir -p packages/$pkg/src/faastlab_askai_$pkg && \
      touch packages/$pkg/src/faastlab_askai_$pkg/__init__.py && \
      touch packages/$pkg/README.md; \
    done

RUN uv sync --frozen --no-dev --all-packages

# ---- Layer 2: actual source (changes often, fast layer) ---------------
COPY packages packages
COPY corpus corpus

EXPOSE 8000

CMD ["uvicorn", "faastlab_askai_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
