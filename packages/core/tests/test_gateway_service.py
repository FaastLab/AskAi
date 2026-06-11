"""Unit tests for the AI gateway (#4) slice 4: the AIGateway facade.

A fake LLM adapter stands in for a real provider; routing, the tenant-row
load, and ledger writes are stubbed so the test isolates the facade's
orchestration: route -> quota -> dispatch -> record (incl. error path).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.exceptions import QuotaExceeded
from faastlab_askai_core.gateway import AIGateway, GatewayContext, ModelRoute
from faastlab_askai_core.gateway import service as service_mod


class FakeAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.seen_model: str | None = None

    async def complete(self, messages, *, model=None, temperature=0.0, max_tokens=None):
        self.seen_model = model
        if self.fail:
            raise RuntimeError("boom")
        return "ANSWER"

    async def stream(self, messages, *, model=None, temperature=0.0, max_tokens=None):
        self.seen_model = model
        for tok in ("a", "b", "c"):
            yield tok


class AllowQuota:
    async def enforce(self, ctx, *, tenant_settings=None):
        return None


class DenyQuota:
    async def enforce(self, ctx, *, tenant_settings=None):
        raise QuotaExceeded("nope", limit_kind="requests", limit=1, used=1)


def _ctx() -> GatewayContext:
    return GatewayContext(tenant_id=uuid4(), tenant_slug="acme", user_id="u1", purpose="chat")


def _wire(monkeypatch, adapter, *, recorded: list) -> None:
    async def _ts(_tid):
        return {}

    async def _record(ctx, usage):
        recorded.append(usage)

    monkeypatch.setattr(service_mod, "load_tenant_settings", _ts)
    monkeypatch.setattr(service_mod, "record_usage", _record)
    monkeypatch.setattr(service_mod, "get_llm_for", lambda provider: adapter)
    monkeypatch.setattr(
        service_mod, "resolve_route", lambda ts, purpose: ModelRoute("ollama", "qwen2.5-32b", purpose)
    )


async def test_complete_dispatches_routes_and_records(monkeypatch) -> None:
    adapter = FakeAdapter()
    recorded: list = []
    _wire(monkeypatch, adapter, recorded=recorded)

    gw = AIGateway(quota=AllowQuota())
    result = await gw.complete(_ctx(), [LLMMessage(role="user", content="hello there")])

    assert result.text == "ANSWER"
    assert result.route.model == "qwen2.5-32b"
    assert adapter.seen_model == "qwen2.5-32b"  # routed model passed to adapter
    assert len(recorded) == 1
    assert recorded[0].status == "ok"
    assert recorded[0].completion_tokens > 0
    assert recorded[0].provider == "ollama"


async def test_complete_blocks_on_quota_before_calling_model(monkeypatch) -> None:
    adapter = FakeAdapter()
    recorded: list = []
    _wire(monkeypatch, adapter, recorded=recorded)

    gw = AIGateway(quota=DenyQuota())
    with pytest.raises(QuotaExceeded):
        await gw.complete(_ctx(), [LLMMessage(role="user", content="hello")])

    assert adapter.seen_model is None  # model never called
    assert recorded == []  # no ok-usage row written for a blocked call


async def test_complete_records_error_and_reraises(monkeypatch) -> None:
    adapter = FakeAdapter(fail=True)
    recorded: list = []
    _wire(monkeypatch, adapter, recorded=recorded)

    gw = AIGateway(quota=AllowQuota())
    with pytest.raises(RuntimeError):
        await gw.complete(_ctx(), [LLMMessage(role="user", content="hello")])

    assert len(recorded) == 1
    assert recorded[0].status == "error"
    assert "boom" in (recorded[0].error or "")


async def test_stream_yields_and_records(monkeypatch) -> None:
    adapter = FakeAdapter()
    recorded: list = []
    _wire(monkeypatch, adapter, recorded=recorded)

    gw = AIGateway(quota=AllowQuota())
    tokens = [t async for t in gw.stream(_ctx(), [LLMMessage(role="user", content="q")])]

    assert tokens == ["a", "b", "c"]
    assert len(recorded) == 1
    assert recorded[0].status == "ok"
    assert recorded[0].completion_tokens > 0  # from "abc"
