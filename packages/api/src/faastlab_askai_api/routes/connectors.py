"""Web-connector management (#8): config-driven crawl sources + indexer dashboard.

Owner-scoped CRUD over a tenant's web connectors plus a manual 'run now' that
enqueues the crawl on the indexing worker, and a per-connector run history.
Config + capped run history live in `tenant.settings["connectors"]` (JSONB
overlay — no schema migration), read/written here and by the worker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import require_scope
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.connectors import (
    find_connector,
    list_connectors,
    normalize_connector,
    remove_connector,
    upsert_connector,
)
from faastlab_askai_core.db import Tenant, get_sessionmaker

router = APIRouter(tags=["connectors"], prefix="/connectors")


class ConnectorBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    mode: str = "crawl"  # page | sitemap | crawl
    start_urls: list[str] = Field(default_factory=list)
    url_prefix: str | None = None
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    max_pages: int = 50
    max_depth: int = 2
    doc_type: str | None = None
    enabled: bool = True
    schedule_interval_minutes: int | None = None


async def _load_settings(session, tenant_id) -> dict:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return dict(tenant.settings or {})


def _save_items(settings: dict, items: list[dict]) -> dict:
    block = dict(settings.get("connectors") or {})
    block["items"] = items
    settings["connectors"] = block
    return settings


@router.get("")
async def get_connectors(
    principal: Principal = Depends(require_scope("owner")),
) -> list[dict]:
    """All connectors for the tenant (with their run history)."""
    sm = get_sessionmaker()
    async with sm() as session:
        settings = (
            await session.execute(
                select(Tenant.settings).where(Tenant.id == principal.tenant_id)
            )
        ).scalar_one_or_none()
    return list_connectors(settings)


@router.post("", status_code=201)
async def create_connector(
    body: ConnectorBody,
    principal: Principal = Depends(require_scope("owner")),
) -> dict:
    connector = normalize_connector(body.model_dump())
    connector["id"] = uuid4().hex
    connector["created_at"] = datetime.now(UTC).isoformat()
    connector["runs"] = []
    sm = get_sessionmaker()
    async with sm() as session:
        tenant = await session.get(Tenant, principal.tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        settings = dict(tenant.settings or {})
        items = upsert_connector(list_connectors(settings), connector)
        tenant.settings = _save_items(settings, items)
        await session.commit()
    await record_action(
        principal=principal,
        action="connector.create",
        resource=f"/v1/connectors/{connector['id']}",
        extra={"id": connector["id"], "name": connector["name"], "mode": connector["mode"]},
    )
    return connector


@router.put("/{connector_id}")
async def update_connector(
    connector_id: str,
    body: ConnectorBody,
    principal: Principal = Depends(require_scope("owner")),
) -> dict:
    sm = get_sessionmaker()
    async with sm() as session:
        tenant = await session.get(Tenant, principal.tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        settings = dict(tenant.settings or {})
        existing = find_connector(settings, connector_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="connector not found")
        # Preserve server-managed fields across the edit.
        merged = {**body.model_dump(), "id": connector_id}
        for key in ("created_at", "last_run_at", "last_run_epoch", "runs"):
            if key in existing:
                merged[key] = existing[key]
        connector = normalize_connector(merged)
        items = upsert_connector(list_connectors(settings), connector)
        tenant.settings = _save_items(settings, items)
        await session.commit()
    await record_action(
        principal=principal,
        action="connector.update",
        resource=f"/v1/connectors/{connector_id}",
        extra={"id": connector_id, "name": connector["name"]},
    )
    return connector


@router.delete("/{connector_id}")
async def delete_connector(
    connector_id: str,
    principal: Principal = Depends(require_scope("owner")),
) -> dict[str, str]:
    sm = get_sessionmaker()
    async with sm() as session:
        tenant = await session.get(Tenant, principal.tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        settings = dict(tenant.settings or {})
        if find_connector(settings, connector_id) is None:
            raise HTTPException(status_code=404, detail="connector not found")
        items = remove_connector(list_connectors(settings), connector_id)
        tenant.settings = _save_items(settings, items)
        await session.commit()
    await record_action(
        principal=principal,
        action="connector.delete",
        resource=f"/v1/connectors/{connector_id}",
        extra={"id": connector_id},
    )
    return {"status": "deleted", "id": connector_id}


@router.post("/{connector_id}/run")
async def run_connector_now(
    connector_id: str,
    principal: Principal = Depends(require_scope("owner")),
) -> dict[str, str]:
    """Enqueue an immediate crawl on the indexing worker. The run is recorded
    in the connector's history when the worker finishes."""
    sm = get_sessionmaker()
    async with sm() as session:
        settings = await _load_settings(session, principal.tenant_id)
    if find_connector(settings, connector_id) is None:
        raise HTTPException(status_code=404, detail="connector not found")

    try:
        from faastlab_askai_indexing.tasks import run_web_connector

        async_result = run_web_connector.delay(str(principal.tenant_id), connector_id)
        task_id = getattr(async_result, "id", "")
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not enqueue crawl — the indexing worker/broker may be down: {exc}",
        ) from exc

    await record_action(
        principal=principal,
        action="connector.run",
        resource=f"/v1/connectors/{connector_id}/run",
        extra={"id": connector_id, "task_id": task_id},
    )
    return {"status": "queued", "task_id": task_id, "id": connector_id}


@router.get("/{connector_id}/runs")
async def get_connector_runs(
    connector_id: str,
    principal: Principal = Depends(require_scope("owner")),
) -> list[dict]:
    sm = get_sessionmaker()
    async with sm() as session:
        settings = (
            await session.execute(
                select(Tenant.settings).where(Tenant.id == principal.tenant_id)
            )
        ).scalar_one_or_none()
    connector = find_connector(settings, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="connector not found")
    return list(connector.get("runs") or [])
