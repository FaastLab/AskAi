"""Pydantic Settings — single source of truth for all runtime config.

Loaded from environment variables (and a `.env` file in dev). Every other
package imports `get_settings()` rather than reading `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """Walk up from this file to find the project-root `.env`.

    Without this, running tools from a subdir (e.g. `cd packages/core &&
    alembic upgrade head` in the Makefile) makes Pydantic Settings look
    for `.env` relative to cwd and silently fall back to defaults — which
    led to migrations connecting to the wrong Postgres on port 5432.
    """
    here = Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        env = candidate / ".env"
        if env.exists():
            return env
        if (candidate / "pyproject.toml").exists() and (candidate / "packages").is_dir():
            # Found the workspace root — stop even if no .env is present.
            return env if env.exists() else None
    return None

# Provider literals — adding a new adapter means adding it here too.
LLMProvider = Literal["openai", "azure", "anthropic", "bedrock", "ollama"]
EmbeddingsProvider = Literal["openai", "azure", "cohere", "huggingface", "ollama"]
StorageProvider = Literal["minio", "s3", "azure-blob"]
VectorStoreProvider = Literal["pgvector", "qdrant", "azure-ai-search", "pinecone"]
RerankerProvider = Literal["cohere", "bge", "none"]
AuthProvider = Literal["jwt", "oidc", "entra", "auth0"]
ObservabilityProvider = Literal["langfuse", "langsmith", "none"]
PdfParser = Literal["pymupdf", "unstructured", "docling"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----
    app_env: Literal["dev", "staging", "prod"] = "dev"
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    app_log_format: Literal["pretty", "json"] = "pretty"

    # ---- Database ----
    database_url: str = "postgresql+asyncpg://askai:askai@localhost:5432/askai"

    # ---- Redis / queue ----
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ---- Storage ----
    storage_provider: StorageProvider = "minio"
    minio_endpoint: str = "http://localhost:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"
    minio_bucket: str = "askai"
    minio_region: str = "us-east-1"

    # ---- LLM ----
    # llm_model is the high-quality answer model (Ask AI, validator).
    # summarisation_model defaults to a cheaper/higher-RPM tier so the
    # demo-corpus auto-summarise pass doesn't burn through chat quotas.
    llm_provider: LLMProvider = "openai"
    llm_model: str = "gpt-4o"
    summarisation_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-08-01-preview"
    azure_openai_deployment: str | None = None
    # Ollama (local / GPU pod) — used when LLM_PROVIDER=ollama. The
    # Ollama daemon must be reachable at OLLAMA_BASE_URL with the model
    # tag named in LLM_MODEL pulled (e.g. `ollama pull qwen2.5:32b`).
    ollama_base_url: str = "http://localhost:11434"

    # ---- Embeddings ----
    # NB: pgvector's HNSW index caps at 2000 dimensions, so the default is
    # 1536 (text-embedding-3-small). To use text-embedding-3-large, reduce
    # via the OpenAI `dimensions` parameter to ≤2000 (Matryoshka).
    embeddings_provider: EmbeddingsProvider = "openai"
    embeddings_model: str = "text-embedding-3-small"
    embeddings_dim: int = 1536

    # ---- Reranker ----
    # Default 'bge' — BAAI/bge-reranker-large (MIT licence). 100% OSS,
    # runs locally via sentence-transformers + torch (install with the
    # [bge-reranker] extra). 'cohere' is a managed alternative. 'none'
    # is pass-through for lean installs without torch.
    reranker_provider: RerankerProvider = "bge"
    cohere_api_key: str | None = None
    # bge-reranker-base is ~5x faster than -large on CPU with comparable
    # quality on regulator Q&A. Switch to -large only if you've got a GPU
    # or the latency budget. -v2-m3 is best quality but heavier.
    bge_reranker_model: str = "BAAI/bge-reranker-base"

    # ---- Vector store ----
    vector_store: VectorStoreProvider = "pgvector"
    vector_index_type: Literal["hnsw", "ivfflat"] = "hnsw"
    vector_hnsw_m: int = 16
    vector_hnsw_ef_construction: int = 64

    # ---- Auth ----
    auth_provider: AuthProvider = "jwt"
    jwt_secret: str = Field(default="change-me-in-prod-please-use-a-long-random-string")
    jwt_algorithm: str = "HS256"
    jwt_audience: str = "askai"
    jwt_issuer: str = "faastlab-askai"

    # ---- Tenancy ----
    default_tenant: str = "demo-public"

    # ---- BYOK (bring your own LLM key) ----
    # When True, /v1/ask and /v1/search require an X-OpenAI-API-Key header
    # — the server's OPENAI_API_KEY is never used for those calls. Use this
    # for public live demos so visitors burn their own quota.
    require_byok: bool = False

    # ---- API ----
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:3000"
    api_rate_limit_per_min: int = 60

    # ---- Observability ----
    observability_provider: ObservabilityProvider = "langfuse"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    sentry_dsn: str | None = None

    # ---- Indexing ----
    chunk_size_tokens: int = 700
    chunk_overlap_tokens: int = 100
    pdf_parser: PdfParser = "pymupdf"
    parser_fallback: PdfParser = "unstructured"

    # ---- Watcher (regulator change feed) ----
    # Polls UK regulator RSS feeds and persists new publications. Disabled
    # by default; flip WATCHER_ENABLED=true in the worker env to switch on.
    watcher_enabled: bool = False
    watcher_tenant_slug: str = "demo-public"
    watcher_poll_interval_seconds: int = 3600  # hourly by default
    watcher_user_agent: str = "FaastLab-AskAi-Watcher/0.1 (+https://faastlab.ai)"
    # Generic webhook — POSTs new events as JSON. Leave None to skip.
    watcher_webhook_url: str | None = None
    # Per-regulator feed URLs (override if a regulator moves a feed).
    watcher_fca_url: str = "https://www.fca.org.uk/news/rss.xml"
    watcher_boe_url: str = "https://www.bankofengland.co.uk/rss/news"
    watcher_pra_url: str = (
        "https://www.bankofengland.co.uk/rss/prudential-regulation/publications"
    )
    watcher_fos_url: str = "https://www.financial-ombudsman.org.uk/rss/news"
    watcher_tpr_url: str = "https://www.thepensionsregulator.gov.uk/rss/news"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    Cached so config is parsed once per process. Tests can call
    `get_settings.cache_clear()` to reload between cases.
    """
    return Settings()
