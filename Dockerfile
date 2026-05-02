# Production image — runs the FastAPI app or a Celery worker depending
# on the command (see Helm chart).

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

# Copy lockfiles first for cache reuse.
COPY pyproject.toml uv.lock* ./
COPY packages packages
COPY corpus corpus

RUN uv sync --frozen --no-dev --all-packages

EXPOSE 8000

CMD ["uvicorn", "faastlab_askai_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
