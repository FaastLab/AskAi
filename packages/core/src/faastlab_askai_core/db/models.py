"""SQLAlchemy 2.x ORM models for AskAi.

Every table carries `tenant_id` for multi-tenant isolation. The
application layer filters by `tenant_id` on every query; row-level
security policies on the database serve as a backstop (set up in the
initial Alembic migration).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from faastlab_askai_core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base. All ORM models inherit from this."""

    type_annotation_map = {dict[str, Any]: JSONB}


# ---- Tenants ----------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    # Trial mode: free until this date, then paywall middleware returns 402.
    # NULL means "no trial limit" (legacy tenants like demo-public, paid
    # customers post-Stripe activation, etc.).
    trial_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Optional plan tier — informational for now; Stripe integration will
    # update this to "starter" | "team" | "firm" when wired up.
    plan: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    documents: Mapped[list["Document"]] = relationship(back_populates="tenant")
    users: Mapped[list["User"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


# ---- Users ------------------------------------------------------------------


class User(Base):
    """Tenant member with login credentials.

    Email is the login identifier and globally unique — one human, one
    account, can be invited into multiple tenants in v2. For Pro v0.1
    each user belongs to exactly one tenant; multi-tenant membership is
    a join-table refactor later.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 'owner' (created the tenant), 'admin' (invited admin), 'member'.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")


# ---- Documents --------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_tenant_id", "tenant_id"),
        Index("ix_documents_tenant_doc_type", "tenant_id", "doc_type"),
        Index("ix_documents_effective_date", "effective_date"),
        UniqueConstraint("tenant_id", "source_uri", name="uq_documents_tenant_source"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyphrases: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def folder(self) -> str | None:
        """Virtual folder path (Azure-blob-style prefix) for the documents
        management UI. Stored in `metadata.folder` so there's no schema column
        to migrate — folders are just an organisational overlay, not data the
        engine depends on. `None`/absent means the tenant's root."""
        value = (self.metadata_ or {}).get("folder")
        return value or None


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        Index("ix_document_versions_document_id", "document_id"),
        UniqueConstraint("document_id", "version_label", name="uq_document_version_label"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_label: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="versions")


# ---- Chunks -----------------------------------------------------------------


def _embedding_dim() -> int:
    """Default embedding dim from settings — used at table-definition time."""
    return get_settings().embeddings_dim


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_tenant_id", "tenant_id"),
        Index("ix_chunks_document_id", "document_id"),
        # HNSW + GIN indexes are created in the Alembic migration (raw SQL,
        # since SQLAlchemy can't express HNSW with parameters portably yet).
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(_embedding_dim()), nullable=False)
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")


# ---- Ingestion --------------------------------------------------------------


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("ix_ingestion_jobs_tenant_status", "tenant_id", "status"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---- Chat sessions ----------------------------------------------------------


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_sessions_tenant_user", "tenant_id", "user_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    history: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---- Audit log --------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_log_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(256), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---- AI Gateway: LLM usage ledger -------------------------------------------


class LLMUsage(Base):
    """One row per LLM call routed through the AI gateway.

    This is the cost/quota ledger and the foundation for #5 observability:
    per-request, per-tenant token counts, latency, and cost. Quota checks
    aggregate this table over a rolling window; the observability layer
    queries the same rows for cost-per-tenant and failure replay.

    `status` distinguishes ok / error / quota_denied so denied attempts are
    auditable too. Tokens are best-effort estimates when the provider does
    not return a usage object (e.g. streamed sovereign completions).
    """

    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("ix_llm_usage_tenant_created", "tenant_id", "created_at"),
        Index("ix_llm_usage_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # What the call was for: chat | summarise | validate | embed | ...
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="chat")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ok | error | quota_denied
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---- AI Gateway: versioned prompts ------------------------------------------


class Prompt(Base):
    """A named, versioned prompt template under gateway governance.

    Many versions may exist per `name`; exactly one should be `is_active`
    (the registry returns the active one when no version is requested). Old
    versions are never edited in place — a new version is inserted and
    activation flipped — so the prompt history is auditable and a bad prompt
    can be rolled back by re-activating a prior version.
    """

    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompts_name_version"),
        Index("ix_prompts_name_active", "name", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---- Watcher events ---------------------------------------------------------


class WatcherEvent(Base):
    """One regulator publication captured by the watcher.

    Dedup is enforced by `uq_watcher_events_regulator_external` so
    re-polling the same feed is idempotent — feeds may safely return
    overlapping windows.

    `tenant_id` is the tenant the event is published *to* — typically the
    `demo-public` tenant on the open knowledge base, so new FCA
    publications become searchable as soon as they're ingested. Private
    tier deployments configure their own watcher tenant.
    """

    __tablename__ = "watcher_events"
    __table_args__ = (
        UniqueConstraint(
            "regulator", "external_id", name="uq_watcher_events_regulator_external"
        ),
        Index("ix_watcher_events_tenant_published", "tenant_id", "published_at"),
        Index("ix_watcher_events_regulator", "regulator"),
        Index("ix_watcher_events_ingested", "ingested"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    regulator: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="publication"
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    ingested: Mapped[bool] = mapped_column(default=False, nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    notified: Mapped[bool] = mapped_column(default=False, nullable=False)
    notification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---- Knowledge layer (#7): answer feedback ----------------------------------


class AnswerFeedback(Base):
    """One user reaction to an answer — the signal behind the feedback loop.

    A thumbs up/down (and optional free-text correction) on a `/v1/ask`
    answer, anchored to that answer's `request_id`. The cited documents are
    captured so the signal can be attributed to the chunks/documents that
    produced the answer, which is what lets feedback nudge retrieval ranking
    (see `faastlab_askai_search.feedback`).

    `normalized_query` is the lowercased/whitespace-collapsed question, stored
    alongside the raw `query` so query-specific aggregation is an indexed
    equality lookup rather than a scan + normalise.
    """

    __tablename__ = "answer_feedback"
    __table_args__ = (
        Index("ix_answer_feedback_tenant_created", "tenant_id", "created_at"),
        Index("ix_answer_feedback_tenant_nquery", "tenant_id", "normalized_query"),
        Index("ix_answer_feedback_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # +1 = thumbs up, -1 = thumbs down. (No 0 — absence of a row is neutral.)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The cited documents/chunks shown for the answer being rated.
    document_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---- Ingestion pipeline (Azure-shaped: Source/Skillset/Index/Indexer) --------
#
# The declarative backbone for ingestion. See docs/ingestion-pipeline-design.md.
# Each entity is a thin typed row whose flexible definition lives in a JSONB
# column (decision: "JSON config in a table, with an id" — not one big blob).
#
# `tenant_id` is NULLABLE on Source / Skillset / IndexProfile so a row can be a
# **system preset** (tenant_id IS NULL) — a shared template (e.g. the FCA source
# config) that many tenants' Indexers reference. An Indexer and its runs always
# belong to a concrete tenant (tenant_id NOT NULL): the indexer is what writes
# into a tenant's corpus.


class Source(Base):
    """Where + how to fetch raw documents (a connector definition).

    `kind` selects the connector (web/sitemap/filesystem/s3/govuk_api/rss);
    `config` carries its parameters (start_urls, url_prefix, include/exclude,
    max_pages…). `category` tags the regulator (fca/pra/boe/hmrc/ico/fos) for
    presets. `license` records the basis under which a preset source's data may
    be centrally curated (see design §10)."""

    __tablename__ = "ingestion_sources"
    __table_args__ = (
        Index("ix_ingestion_sources_tenant", "tenant_id"),
        Index("ix_ingestion_sources_category", "category"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="web")
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    license: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_preset: Mapped[bool] = mapped_column(default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Skillset(Base):
    """An ordered, reusable list of enrichment skills.

    `skills` is the ordered pipeline: [{type, config}] over
    parse/clean/chunk/extract_metadata/summarise/keyphrases/embed. The default
    skillset reproduces today's hardcoded `IngestionPipeline` behaviour."""

    __tablename__ = "ingestion_skillsets"
    __table_args__ = (Index("ix_ingestion_skillsets_tenant", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    skills: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IndexProfile(Base):
    """A lightweight field/metadata profile (NOT a mutable DB schema).

    `fields` declares which fields to populate and their flags
    (searchable/filterable/facetable/retrievable). They map onto
    `Document.metadata_` keys + the search/filter layer, so fields can be added
    later without a migration (design §5)."""

    __tablename__ = "ingestion_index_profiles"
    __table_args__ = (Index("ix_ingestion_index_profiles_tenant", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Indexer(Base):
    """Binds a Source + Skillset + IndexProfile + Scheduler and runs them.

    The orchestrator: it pulls from `source`, runs `skillset`, maps outputs to
    `index_profile` fields via `field_mappings`, dedups on `content_hash`, and
    writes into THIS tenant's corpus. `schedule` is {interval_minutes|cron|null}.
    Always tenant-scoped — it's what writes data."""

    __tablename__ = "ingestion_indexers"
    __table_args__ = (Index("ix_ingestion_indexers_tenant", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ingestion_sources.id", ondelete="CASCADE"), nullable=False
    )
    skillset_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ingestion_skillsets.id", ondelete="SET NULL"),
        nullable=True,
    )
    index_profile_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ingestion_index_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    field_mappings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    runs: Mapped[list["IndexerRun"]] = relationship(
        back_populates="indexer", cascade="all, delete-orphan"
    )


class IndexerRun(Base):
    """One execution of an Indexer — the queryable run history.

    Replaces the JSONB run-history of the prototype connector work so runs can
    grow and be queried (counts, status, errors, duration)."""

    __tablename__ = "ingestion_indexer_runs"
    __table_args__ = (
        Index("ix_ingestion_indexer_runs_indexer", "indexer_id", "id"),
        Index("ix_ingestion_indexer_runs_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    indexer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ingestion_indexers.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # running | ok | error
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    log: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    indexer: Mapped[Indexer] = relationship(back_populates="runs")
