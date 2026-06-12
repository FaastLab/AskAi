"""Ingestion pipeline API (#8, Azure-shaped) — presets, indexers, runs.

Owner-scoped surface over the Source/Skillset/IndexProfile/Indexer model
(docs/ingestion-pipeline-design.md). The headline flow: list the shipped
regulator **presets** (FCA/PRA/BoE/HMRC/ICO/TPR, OFF by default), **enable** one
(clones it into a tenant Source + default Skillset/IndexProfile + an Indexer),
then **run** it (enqueues the crawl on the worker) and watch its **run history**.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import require_scope
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import (
    Indexer,
    IndexerRun,
    IndexProfile,
    Skillset,
    Source,
    get_sessionmaker,
)
from faastlab_askai_core.factory import get_storage
from faastlab_askai_core.ingestion import (
    default_index_fields,
    default_skillset_skills,
    find_preset,
    folder_prefix,
    regulator_presets,
    storage_key_for,
)

router = APIRouter(tags=["ingestion"], prefix="/ingestion")


# ---- helpers ---------------------------------------------------------------


async def _default_skillset_id(session, tenant_id: UUID) -> UUID:
    """Find-or-create the tenant's default skillset (today's pipeline behaviour)."""
    existing = (
        await session.execute(
            select(Skillset.id).where(
                Skillset.tenant_id == tenant_id, Skillset.is_default.is_(True)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    sk = Skillset(
        tenant_id=tenant_id,
        name="Standard regulatory text",
        skills=default_skillset_skills(),
        is_default=True,
    )
    session.add(sk)
    await session.flush()
    return sk.id


async def _default_index_profile_id(session, tenant_id: UUID) -> UUID:
    """Find-or-create the tenant's default index field profile."""
    existing = (
        await session.execute(
            select(IndexProfile.id).where(IndexProfile.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    ip = IndexProfile(
        tenant_id=tenant_id, name="UK FinReg", fields=default_index_fields()
    )
    session.add(ip)
    await session.flush()
    return ip.id


def _run_summary(run: IndexerRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "run_id": run.id,
        "status": run.status,
        "pages": run.pages,
        "ingested": run.ingested,
        "skipped": run.skipped,
        "failed": run.failed,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
    }


# ---- presets ---------------------------------------------------------------


@router.get("/presets")
async def list_presets(
    principal: Principal = Depends(require_scope("owner")),
) -> list[dict]:
    """The shipped regulator presets, each marked with whether this tenant has
    already enabled it (so the UI can render a toggle)."""
    sm = get_sessionmaker()
    async with sm() as session:
        enabled_keys = set(
            (
                await session.execute(
                    select(Source.config["preset_key"].astext).where(
                        Source.tenant_id == principal.tenant_id
                    )
                )
            )
            .scalars()
            .all()
        )
    out = []
    for p in regulator_presets():
        out.append(
            {
                "key": p["key"],
                "name": p["name"],
                "category": p["category"],
                "description": p["description"],
                "license": p["license"],
                "kind": p["kind"],
                "start_url_count": len(p["config"].get("start_urls") or []),
                "enabled": p["key"] in enabled_keys,
            }
        )
    return out


@router.post("/presets/{key}/enable", status_code=201)
async def enable_preset(
    key: str,
    principal: Principal = Depends(require_scope("owner")),
) -> dict:
    """Clone a preset into a tenant Source + Indexer (idempotent per preset)."""
    preset = find_preset(key)
    if preset is None:
        raise HTTPException(status_code=404, detail="unknown preset")

    sm = get_sessionmaker()
    async with sm() as session:
        # Idempotent: if already enabled, return the existing indexer.
        existing_source = (
            await session.execute(
                select(Source).where(
                    Source.tenant_id == principal.tenant_id,
                    Source.config["preset_key"].astext == key,
                )
            )
        ).scalar_one_or_none()
        if existing_source is not None:
            indexer = (
                await session.execute(
                    select(Indexer).where(Indexer.source_id == existing_source.id)
                )
            ).scalar_one_or_none()
            if indexer is not None:
                return {"id": str(indexer.id), "already_enabled": True}

        source = Source(
            id=uuid4(),
            tenant_id=principal.tenant_id,
            name=preset["name"],
            kind=preset["kind"],
            category=preset["category"],
            config={**preset["config"], "preset_key": key},
            license=preset["license"],
            is_preset=True,
            enabled=True,
        )
        session.add(source)
        skillset_id = await _default_skillset_id(session, principal.tenant_id)
        index_profile_id = await _default_index_profile_id(session, principal.tenant_id)
        indexer = Indexer(
            id=uuid4(),
            tenant_id=principal.tenant_id,
            name=preset["name"],
            source_id=source.id,
            skillset_id=skillset_id,
            index_profile_id=index_profile_id,
            field_mappings={"regulator": preset["category"]},
            schedule={},
            enabled=True,
        )
        session.add(indexer)
        await session.commit()
        indexer_id = indexer.id

    await record_action(
        principal=principal,
        action="ingestion.preset.enable",
        resource=f"/v1/ingestion/presets/{key}",
        extra={"preset": key, "indexer_id": str(indexer_id)},
    )
    return {"id": str(indexer_id), "already_enabled": False}


# ---- indexers --------------------------------------------------------------


@router.get("/indexers")
async def list_indexers(
    principal: Principal = Depends(require_scope("owner")),
) -> list[dict]:
    """The tenant's indexers with their source + latest run summary."""
    sm = get_sessionmaker()
    async with sm() as session:
        indexers = (
            (
                await session.execute(
                    select(Indexer)
                    .where(Indexer.tenant_id == principal.tenant_id)
                    .order_by(desc(Indexer.created_at))
                )
            )
            .scalars()
            .all()
        )
        out = []
        for ix in indexers:
            source = await session.get(Source, ix.source_id)
            latest = (
                await session.execute(
                    select(IndexerRun)
                    .where(IndexerRun.indexer_id == ix.id)
                    .order_by(desc(IndexerRun.id))
                    .limit(1)
                )
            ).scalar_one_or_none()
            out.append(
                {
                    "id": str(ix.id),
                    "name": ix.name,
                    "enabled": ix.enabled,
                    # source_id + kind let the UI offer "upload files" on folder
                    # sources (and only on folder sources, not web crawls).
                    "source_id": str(source.id) if source else None,
                    "kind": source.kind if source else None,
                    "category": source.category if source else None,
                    "license": source.license if source else None,
                    "preset_key": (source.config or {}).get("preset_key") if source else None,
                    "schedule": ix.schedule,
                    "last_run_at": ix.last_run_at.isoformat() if ix.last_run_at else None,
                    "last_run": _run_summary(latest),
                }
            )
    return out


@router.post("/indexers/{indexer_id}/run")
async def run_indexer_now(
    indexer_id: UUID,
    principal: Principal = Depends(require_scope("owner")),
) -> dict[str, str]:
    """Enqueue an immediate run of this indexer on the worker."""
    sm = get_sessionmaker()
    async with sm() as session:
        ix = await session.get(Indexer, indexer_id)
        if ix is None or ix.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=404, detail="indexer not found")

    try:
        from faastlab_askai_indexing.tasks import run_indexer

        result = run_indexer.delay(str(indexer_id))
        task_id = getattr(result, "id", "")
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not enqueue — the indexing worker/broker may be down: {exc}",
        ) from exc

    await record_action(
        principal=principal,
        action="ingestion.indexer.run",
        resource=f"/v1/ingestion/indexers/{indexer_id}/run",
        extra={"indexer_id": str(indexer_id), "task_id": task_id},
    )
    return {"status": "queued", "task_id": task_id, "id": str(indexer_id)}


@router.get("/indexers/{indexer_id}/runs")
async def list_indexer_runs(
    indexer_id: UUID,
    principal: Principal = Depends(require_scope("owner")),
) -> list[dict]:
    sm = get_sessionmaker()
    async with sm() as session:
        ix = await session.get(Indexer, indexer_id)
        if ix is None or ix.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=404, detail="indexer not found")
        runs = (
            (
                await session.execute(
                    select(IndexerRun)
                    .where(IndexerRun.indexer_id == indexer_id)
                    .order_by(desc(IndexerRun.id))
                    .limit(25)
                )
            )
            .scalars()
            .all()
        )
    return [_run_summary(r) for r in runs]


@router.delete("/indexers/{indexer_id}")
async def delete_indexer(
    indexer_id: UUID,
    principal: Principal = Depends(require_scope("owner")),
) -> dict[str, str]:
    """Remove an indexer + its source (does NOT delete already-ingested docs)."""
    sm = get_sessionmaker()
    async with sm() as session:
        ix = await session.get(Indexer, indexer_id)
        if ix is None or ix.tenant_id != principal.tenant_id:
            raise HTTPException(status_code=404, detail="indexer not found")
        source_id = ix.source_id
        await session.delete(ix)  # cascades indexer_runs
        source = await session.get(Source, source_id)
        if source is not None and source.tenant_id == principal.tenant_id:
            await session.delete(source)
        await session.commit()
    await record_action(
        principal=principal,
        action="ingestion.indexer.delete",
        resource=f"/v1/ingestion/indexers/{indexer_id}",
        extra={"indexer_id": str(indexer_id)},
    )
    return {"status": "deleted", "id": str(indexer_id)}


# ---- custom folder data source (the demo flow) ------------------------------


class FolderSourceBody(BaseModel):
    """Create a folder data source: upload files into it, an indexer on a
    schedule then auto-indexes them."""

    name: str = Field(min_length=1, max_length=128)
    # How often the scheduler should auto-index the folder. None/0 = manual
    # ("Run now") only — no timed runs.
    schedule_interval_minutes: int | None = Field(default=None, ge=0, le=10080)


@router.post("/sources/folder", status_code=201)
async def create_folder_source(
    body: FolderSourceBody,
    principal: Principal = Depends(require_scope("owner")),
) -> dict:
    """Create a folder Source + default Skillset/IndexProfile + an Indexer.

    The Source's files live under a per-source object-storage prefix; uploads go
    there and the indexer reads from there. Returns the ids the UI needs to
    upload files and run/track the indexer."""
    source_id = uuid4()
    # interval 0/None means "manual only"; store a schedule only when timed so
    # the scheduler's due-check (is_indexer_due) treats it correctly.
    schedule: dict = {}
    if body.schedule_interval_minutes:
        schedule = {"interval_minutes": int(body.schedule_interval_minutes)}

    sm = get_sessionmaker()
    async with sm() as session:
        source = Source(
            id=source_id,
            tenant_id=principal.tenant_id,
            name=body.name,
            kind="folder",  # runner reads the object-storage prefix for this kind
            category=None,
            config={"prefix": folder_prefix(source_id)},
            license="byo",  # bring-your-own: the tenant's own uploaded files
            is_preset=False,
            enabled=True,
        )
        session.add(source)
        skillset_id = await _default_skillset_id(session, principal.tenant_id)
        index_profile_id = await _default_index_profile_id(session, principal.tenant_id)
        indexer = Indexer(
            id=uuid4(),
            tenant_id=principal.tenant_id,
            name=body.name,
            source_id=source_id,
            skillset_id=skillset_id,
            index_profile_id=index_profile_id,
            field_mappings={},
            schedule=schedule,
            enabled=True,
        )
        session.add(indexer)
        await session.commit()
        indexer_id = indexer.id

    await record_action(
        principal=principal,
        action="ingestion.source.create",
        resource=f"/v1/ingestion/sources/{source_id}",
        extra={"source_id": str(source_id), "name": body.name, "kind": "folder"},
    )
    return {
        "source_id": str(source_id),
        "indexer_id": str(indexer_id),
        "schedule": schedule,
    }


@router.post("/sources/{source_id}/upload")
async def upload_to_source(
    source_id: UUID,
    files: list[UploadFile] = File(...),
    principal: Principal = Depends(require_scope("owner")),
) -> dict:
    """Upload one or more files into a folder Source's object-storage prefix.

    The files are NOT ingested here — they just land in the folder. The
    indexer (scheduled or "Run now") is what parses + indexes them, which is
    exactly the demo story: drop files in a folder, the pipeline picks them up."""
    sm = get_sessionmaker()
    async with sm() as session:
        source = await session.get(Source, source_id)
        # Only the owning tenant's own folder sources accept uploads.
        if (
            source is None
            or source.tenant_id != principal.tenant_id
            or source.kind != "folder"
        ):
            raise HTTPException(status_code=404, detail="folder source not found")

    storage = get_storage()
    stored: list[str] = []
    for f in files:
        data = await f.read()
        if not data:
            continue  # skip empties rather than writing 0-byte objects
        # storage_key_for strips any path from the filename so an upload can't
        # escape the source's prefix.
        key = storage_key_for(source_id, f.filename or "file")
        await storage.put(key, data, content_type=f.content_type)
        stored.append(f.filename or key)

    await record_action(
        principal=principal,
        action="ingestion.source.upload",
        resource=f"/v1/ingestion/sources/{source_id}/upload",
        extra={"source_id": str(source_id), "files": stored[:50], "count": len(stored)},
    )
    return {"status": "ok", "uploaded": len(stored), "files": stored}
