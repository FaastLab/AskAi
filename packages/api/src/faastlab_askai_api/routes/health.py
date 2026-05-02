"""Health and version endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict[str, str]:
    # TODO(phase 12): probe DB / Redis / MinIO here.
    return {"status": "ready"}


@router.get("/version")
async def version() -> dict[str, str]:
    return {"name": "faastlab-askai", "version": "0.1.0"}
