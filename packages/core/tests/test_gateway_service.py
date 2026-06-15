"""Unit tests for the AI gateway (#4) facade — now with model failover.

A fake LLM adapter stands in for a real provider; the target chain, tenant-row
load, and ledger writes are stubbed so the test isolates the facade's
orchestration: gate (quota) -> walk the target chain -> dispatch -> record,
including the failover path (primary errors -> fallback serves).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.exceptions import LLMError, QuotaExceeded
from faastlab_askai_core.gateway import AIGateway, GatewayContext, ModelTarget
from faastlab_askai_core.gateway import service as service_mod


class FakeAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.seen_model: str | None = None

    async def complete(self, messages, *, model=None, temperature=0.0, max_tokens=None):
        self.seen_model = model
        if self.fail:
            raise LLMError("boom")
        return "ANSWER"

    async def stream(self, messages, *, model=None, temperature=0.0, max_tokens=None):
        self.seen_model = model
        if self.fail:
            raise LLMError("boom")
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


def _target(name: str, model: str) -> ModelTarget:
    return ModelTarget(
        name=name,
        label=name,
        provider="openai",
        model=model,
        base_url="http://x/v1",
        api_key="k",
        configured=True,
    )


def _wire(monkeypatch, *, chain, adapters, recorded: list) -> None:
    """Stub the gateway's external seams. `chain` is the ordered targets;
    `adapters` maps target name -> FakeAdapter."""

    async def _ts(_tid):
        return {}

    async def _record(ctx, usage):
        recorded.append(usage)

    monkeypatch.setattr(service_mod, "load_tenant_settings", _ts)
    monkeypatch.setattr(service_mod, "record_usage", _record)
    monkeypatch.setattr(service_mod, "resolve_target_chain", lambda ts: chain)
    monkeypatch.setattr(
        service_mod, "get_llm_for_target", lambda target: adapters[target.name]
    )


async def test_complete_dispatches_and_records(monkeypatch) -> None:
    adapter = FakeAdapter()
    recorded: list = []
    _wire(
        monkeypatch,
        chain=[_target("qwen", "qwen2.5-14b")],
        adapters={"qwen": adapter},
        recorded=recorded,
    )

    gw = AIGateway(quota=AllowQuota())
    result = await gw.complete(_ctx(), [LLMMessage(role="user", content="hello there")])

    assert result.text == "ANSWER"
    assert result.route.model == "qwen2.5-14b"
    assert adapter.seen_model == "qwen2.5-14b"
    assert len(recorded) == 1
    assert recorded[0].status == "ok"
    assert recorded[0].completion_tokens > 0


async def test_complete_blocks_on_quota_before_calling_model(monkeypatch) -> None:
    adapter = FakeAdapter()
    recorded: list = []
    _wire(
        monkeypatch,
        chain=[_target("qwen", "qwen2.5-14b")],
        adapters={"qwen": adapter},
        recorded=recorded,
    )

    gw = AIGateway(quota=DenyQuota())
    with pytest.raises(QuotaExceeded):
        await gw.complete(_ctx(), [LLMMessage(role="user", content="hello")])

    assert adapter.seen_model is None  # model never called
    assert recorded == []  # no usage row written for a blocked call


async def test_single_target_failure_reraises_no_failover(monkeypatch) -> None:
    """One target = no failover: the error propagates, one error row recorded."""
    adapter = FakeAdapter(fail=True)
    recorded: list = []
    _wire(
        monkeypatch,
        chain=[_target("qwen", "qwen2.5-14b")],
        adapters={"qwen": adapter},
        recorded=recorded,
    )

    gw = AIGateway(quota=AllowQuota())
    with pytest.raises(LLMError):
        await gw.complete(_ctx(), [LLMMessage(role="user", content="hello")])

    assert len(recorded) == 1
    assert recorded[0].status == "error"
    assert "boom" in (recorded[0].error or "")


async def test_complete_fails_over_to_second_target(monkeypatch) -> None:
    """Both targets selected: Qwen errors → OpenAI serves the answer."""
    primary = FakeAdapter(fail=True)
    fallback = FakeAdapter()
    recorded: list = []
    _wire(
        monkeypatch,
        chain=[_target("qwen", "qwen2.5-14b"), _target("openai", "gpt-4o-mini")],
        adapters={"qwen": primary, "openai": fallback},
        recorded=recorded,
    )

    gw = AIGateway(quota=AllowQuota())
    result = await gw.complete(_ctx(), [LLMMessage(role="user", content="hello")])

    assert result.text == "ANSWER"
    assert result.route.model == "gpt-4o-mini"  # served by the fallback
    assert fallback.seen_model == "gpt-4o-mini"
    # One error row (primary) + one ok row (fallback).
    assert [r.status for r in recorded] == ["error", "ok"]


async def test_complete_all_targets_fail_reraises(monkeypatch) -> None:
    recorded: list = []
    _wire(
        monkeypatch,
        chain=[_target("qwen", "q"), _target("openai", "o")],
        adapters={"qwen": FakeAdapter(fail=True), "openai": FakeAdapter(fail=True)},
        recorded=recorded,
    )

    gw = AIGateway(quota=AllowQuota())
    with pytest.raises(LLMError):
        await gw.complete(_ctx(), [LLMMessage(role="user", content="x")])
    assert [r.status for r in recorded] == ["error", "error"]


async def test_stream_yields_and_records(monkeypatch) -> None:
    adapter = FakeAdapter()
    recorded: list = []
    _wire(
        monkeypatch,
        chain=[_target("qwen", "qwen2.5-14b")],
        adapters={"qwen": adapter},
        recorded=recorded,
    )

    gw = AIGateway(quota=AllowQuota())
    tokens = [t async for t in gw.stream(_ctx(), [LLMMessage(role="user", content="q")])]

    assert tokens == ["a", "b", "c"]
    assert len(recorded) == 1
    assert recorded[0].status == "ok"


async def test_stream_fails_over_before_first_token(monkeypatch) -> None:
    """A stream target that errors before emitting can still fail over."""
    recorded: list = []
    _wire(
        monkeypatch,
        chain=[_target("qwen", "q"), _target("openai", "o")],
        adapters={"qwen": FakeAdapter(fail=True), "openai": FakeAdapter()},
        recorded=recorded,
    )

    gw = AIGateway(quota=AllowQuota())
    tokens = [t async for t in gw.stream(_ctx(), [LLMMessage(role="user", content="q")])]
    assert tokens == ["a", "b", "c"]  # served by the fallback
