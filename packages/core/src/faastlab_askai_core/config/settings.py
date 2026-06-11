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
RerankerProvider = Literal["cohere", "bge", "tei", "none"]
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
    # 'bge'    — local cross-encoder via sentence-transformers + torch (CPU
    #            heavy on a VM). 'cohere' — managed. 'tei' — sovereign: calls
    #            the GPU box's TEI reranker over HTTP (fast, no torch on the
    #            VM). 'none' — pass-through. For the sovereign CPU-VM + GPU
    #            split, use 'tei' with RERANKER_BASE_URL → the GPU :8081.
    reranker_provider: RerankerProvider = "bge"
    cohere_api_key: str | None = None
    # bge-reranker-base is ~5x faster than -large on CPU with comparable
    # quality on regulator Q&A. Switch to -large only if you've got a GPU
    # or the latency budget. -v2-m3 is best quality but heavier.
    bge_reranker_model: str = "BAAI/bge-reranker-base"
    # TEI reranker endpoint (provider='tei'). The GPU box's bge-reranker on
    # HF Text-Embeddings-Inference, e.g. http://100.92.179.115:8081 — bge-m3
    # reranker, GPU-served. No model field: TEI serves one model per process.
    reranker_base_url: str | None = None

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
    jwt_token_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days
    # Trial mode: new sign-ups get this many days of free use before the
    # paywall middleware returns 402. Set to 0 to disable (everyone in
    # trial mode forever — useful for closed-beta phases).
    trial_default_days: int = 14

    # ---- Tenancy ----
    default_tenant: str = "demo-public"
    # The tenant whose documents are considered "public regulator corpus" —
    # every signed-in tenant gets read access to these docs (FCA Handbook,
    # HMRC manuals, watcher events) IN ADDITION to their own private uploads.
    # Set to None or empty to disable the shared-corpus union (single-tenant mode).
    public_corpus_tenant_slug: str | None = "demo-public"

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

    # ---- AI Gateway (#4) ----
    # Single chokepoint for LLM access: per-tenant quotas, model routing,
    # versioned prompts, and a usage/cost ledger. All limits default to 0 =
    # UNLIMITED so enabling the gateway never silently throttles an existing
    # tenant — per-tenant caps are opt-in via `tenant.settings["gateway"]`.
    gateway_enabled: bool = True
    # Rolling 24h caps applied per tenant when > 0. A tenant's own
    # settings["gateway"]["quota"] overrides these defaults.
    gateway_default_requests_per_day: int = 0
    gateway_default_tokens_per_day: int = 0
    # Cost ledger: price per 1k total tokens. Default 0.0 — sovereign models
    # (Qwen on our own GPU) have no per-token cost. Set per-deployment when
    # routing to a metered provider (e.g. OpenAI) so cost-per-tenant is real.
    gateway_price_per_1k_tokens: float = 0.0

    # ---- MCP (Streamable HTTP transport) ----
    # When set, mounts an HTTP MCP endpoint at /mcp gated by a shared
    # bearer token. Customers point Claude Desktop / VS Code Copilot /
    # any MCP-aware agent at https://<host>/mcp with this token. Leave
    # blank to disable the HTTP transport (stdio still works via
    # `python -m faastlab_askai_mcp.server`). For demo-grade deploys
    # only — multi-tenant scoping comes later (today: pinned to
    # default_tenant on whichever instance the API runs on).
    mcp_shared_token: str | None = None

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

    # FOS final decisions are published in batches and don't change often,
    # so we ingest them on a separate, slower schedule (default: daily).
    # Set to 0 to disable.
    fos_ingest_enabled: bool = False
    fos_ingest_interval_seconds: int = 24 * 3600  # daily
    fos_ingest_max_pages: int = 10  # ~100 newest decisions per run
    watcher_user_agent: str = "FaastLab-AskAi-Watcher/0.1 (+https://faastlab.ai)"
    # Generic webhook — POSTs new events as JSON. Leave None to skip.
    watcher_webhook_url: str | None = None
    # Per-regulator feed URLs (override if a regulator moves a feed).
    watcher_fca_url: str = "https://www.fca.org.uk/news/rss.xml"
    watcher_boe_url: str = "https://www.bankofengland.co.uk/rss/news"
    # PRA shares BoE infrastructure; the publications feed covers PRA materials.
    watcher_pra_url: str = "https://www.bankofengland.co.uk/rss/publications"
    # FOS doesn't publish a stable RSS — leave blank to skip; a future scrape adapter will fill this.
    watcher_fos_url: str = ""
    # TPR + ICO + HMRC all expose gov.uk Atom feeds (the most reliable RSS in UK gov).
    watcher_tpr_url: str = (
        "https://www.gov.uk/government/organisations/the-pensions-regulator.atom"
    )
    watcher_ico_url: str = (
        "https://www.gov.uk/government/organisations/information-commissioner-s-office.atom"
    )
    watcher_hmrc_url: str = (
        "https://www.gov.uk/government/organisations/hm-revenue-customs.atom"
    )
    # Auto-ingest: when True, the watcher fetches each new event's URL and
    # runs it through the ingestion pipeline so it becomes searchable in
    # the corpus within one poll cycle of being published.
    watcher_auto_ingest: bool = False

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
