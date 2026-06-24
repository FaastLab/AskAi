"""Document enrichment — customer self-serve summaries + keyphrases (owner-only).

The toggle that replaces "an admin runs a CLI command": the customer turns
auto-enrichment on for their tenant, sees how many of their documents are
enriched, and clicks "Enrich remaining" for any backlog. New documents then
self-enrich on ingest, and a background sweep heals anything left — no commands.

Settings live in `tenant.settings["enrichment"]` (JSONB; no migration).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import require_scope
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.config import get_settings
from faastlab_askai_core.db import Document, Tenant, get_sessionmaker
from faastlab_askai_core.enrichment import enrichment_enabled, with_enrichment

router = APIRouter(tags=["enrichment"], prefix="/enrichment")


class EnrichmentSettings(BaseModel):
    # auto = generate summaries + keyphrases for documents as they're ingested.
    auto: bool
    # The deployment default, shown so the UI can explain "off → uses default".
    default: bool


class EnrichmentUpdate(BaseModel):
    auto: bool


class EnrichmentStatus(BaseModel):
    total: int  # documents owned by this tenant
    enriched: int  # documents that have a summary
    pending: int  # documents still missing a summary


@router.get("", response_model=EnrichmentSettings)
async def get_enrichment(
    principal: Principal = Depends(require_scope("owner")),
) -> EnrichmentSettings:
    """The tenant's auto-enrichment toggle (+ the deployment default)."""
    default = get_settings().summarise_on_ingest
    sm = get_sessionmaker()
    async with sm() as session:
        settings = (
            await session.execute(
                select(Tenant.settings).where(Tenant.id == principal.tenant_id)
            )
        ).scalar_one_or_none()
    return EnrichmentSettings(
        auto=enrichment_enabled(settings, default=default), default=default
    )


@router.put("", response_model=EnrichmentSettings)
async def set_enrichment(
    body: EnrichmentUpdate,
    principal: Principal = Depends(require_scope("owner")),
) -> EnrichmentSettings:
    """Turn auto-enrichment on/off for the tenant. New ingests honour it
    immediately; the background sweep then enriches any existing backlog."""
    default = get_settings().summarise_on_ingest
    sm = get_sessionmaker()
    async with sm() as session:
        tenant = await session.get(Tenant, principal.tenant_id)
        if tenant is not None:
            # Reassign so SQLAlchemy flags the JSONB column dirty.
            tenant.settings = with_enrichment(tenant.settings, auto=body.auto)
            await session.commit()
    await record_action(
        principal=principal,
        action="enrichment.update",
        resource="/v1/enrichment",
        extra={"auto": body.auto},
    )
    return EnrichmentSettings(auto=body.auto, default=default)


@router.get("/status", response_model=EnrichmentStatus)
async def enrichment_status(
    principal: Principal = Depends(require_scope("owner")),
) -> EnrichmentStatus:
    """How many of the tenant's documents have a summary yet — powers the
    progress bar on the data-sources page."""
    sm = get_sessionmaker()
    async with sm() as session:
        total = (
            await session.execute(
                select(func.count(Document.id)).where(
                    Document.tenant_id == principal.tenant_id
                )
            )
        ).scalar_one()
        # "enriched" = has a non-empty summary.
        enriched = (
            await session.execute(
                select(func.count(Document.id)).where(
                    Document.tenant_id == principal.tenant_id,
                    Document.summary.is_not(None),
                    Document.summary != "",
                )
            )
        ).scalar_one()
    total = int(total or 0)
    enriched = int(enriched or 0)
    return EnrichmentStatus(
        total=total, enriched=enriched, pending=max(0, total - enriched)
    )
