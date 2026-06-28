"""Smoke tests for the voice (STT/TTS) routes — they're registered and reject
bad/unauth input without reaching OpenAI."""

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
async def test_speak_route_registered_and_validates(client) -> None:
    # Missing 'text' → validation/auth error, but NOT 404 (route exists).
    r = await client.post("/v1/voice/speak", json={})
    assert r.status_code != 404
    assert r.status_code in (401, 403, 422)


@pytest.mark.asyncio
async def test_transcribe_route_registered_and_requires_file(client) -> None:
    r = await client.post("/v1/voice/transcribe")
    assert r.status_code != 404
    assert r.status_code in (401, 403, 422)
