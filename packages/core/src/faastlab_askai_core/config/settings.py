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
EmbeddingsProvider = Literal["openai", "azure", "cohere", "huggingface"]
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
    bge_reranker_model: str = "BAAI/bge-reranker-large"

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
