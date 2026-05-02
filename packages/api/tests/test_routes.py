"""Smoke tests for the FastAPI surface."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from faastlab_askai_api.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_healthz_ok(client) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_version_endpoint(client) -> None:
    r = await client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "faastlab-askai"
    assert "version" in body


@pytest.mark.asyncio
async def test_unauth_endpoints_dev_mode_default(client) -> None:
    """In APP_ENV=dev (the default), unauthenticated calls bind to default tenant."""
    r = await client.get("/v1/tenants/me")
    # Either 200 (default tenant exists) or 503 (DB not running) — both
    # confirm the route + auth dep wired up correctly without crashing.
    assert r.status_code in (200, 503)
