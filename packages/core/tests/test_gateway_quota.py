"""Unit tests for the AI gateway (#4) slice 1: quotas + usage ledger.

DB-touching methods are stubbed so these run without a live Postgres — the
logic under test is limit resolution, token/cost estimation, and the
allow/deny/raise decision.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from faastlab_askai_core.exceptions import QuotaExceeded
from faastlab_askai_core.gateway import (
    GatewayContext,
    QuotaLimits,
    QuotaService,
    QuotaStatus,
    QuotaUsage,
    estimate_cost_usd,
    estimate_tokens,
    resolve_limits,
    usage_from_text,
)
from faastlab_askai_core.gateway import quota as quota_mod
from faastlab_askai_core.gateway import usage as usage_mod


def _settings(**over):
    base = dict(
        gateway_enabled=True,
        gateway_default_requests_per_day=0,
        gateway_default_tokens_per_day=0,
        gateway_price_per_1k_tokens=0.0,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _ctx() -> GatewayContext:
    return GatewayContext(tenant_id=uuid4(), tenant_slug="acme", user_id="u1", purpose="chat")


# ---- token + cost estimation ------------------------------------------------


def test_estimate_tokens_empty_is_zero() -> None:
    assert estimate_tokens("") == 0


def test_estimate_tokens_positive_for_text() -> None:
    assert estimate_tokens("the quick brown fox jumps") > 0


def test_estimate_cost_zero_for_sovereign(monkeypatch) -> None:
    monkeypatch.setattr(usage_mod, "get_settings", lambda: _settings())
    assert estimate_cost_usd(10_000) == 0.0


def test_estimate_cost_uses_price(monkeypatch) -> None:
    monkeypatch.setattr(usage_mod, "get_settings", lambda: _settings(gateway_price_per_1k_tokens=2.0))
    # 1000 tokens * $2/1k = $2.00
    assert estimate_cost_usd(1000) == pytest.approx(2.0)


def test_usage_from_text_sums_tokens(monkeypatch) -> None:
    monkeypatch.setattr(usage_mod, "get_settings", lambda: _settings())
    rec = usage_from_text(prompt="hello world", completion="hi there", model="qwen", provider="ollama")
    assert rec.total_tokens == rec.prompt_tokens + rec.completion_tokens
    assert rec.prompt_tokens > 0 and rec.completion_tokens > 0
    assert rec.model == "qwen" and rec.provider == "ollama"
    assert rec.status == "ok"


# ---- limit resolution -------------------------------------------------------


def test_resolve_limits_defaults_unlimited(monkeypatch) -> None:
    monkeypatch.setattr(quota_mod, "get_settings", lambda: _settings())
    limits = resolve_limits(None)
    assert limits == QuotaLimits(0, 0)
    assert not limits.has_any


def test_resolve_limits_global_default(monkeypatch) -> None:
    monkeypatch.setattr(
        quota_mod, "get_settings",
        lambda: _settings(gateway_default_requests_per_day=500, gateway_default_tokens_per_day=1_000_000),
    )
    limits = resolve_limits(None)
    assert limits.requests_per_day == 500
    assert limits.tokens_per_day == 1_000_000
    assert limits.has_any


def test_resolve_limits_tenant_override_beats_default(monkeypatch) -> None:
    monkeypatch.setattr(
        quota_mod, "get_settings",
        lambda: _settings(gateway_default_requests_per_day=500),
    )
    tenant_settings = {"gateway": {"quota": {"requests_per_day": 50, "tokens_per_day": 9}}}
    limits = resolve_limits(tenant_settings)
    assert limits.requests_per_day == 50
    assert limits.tokens_per_day == 9


def test_resolve_limits_ignores_garbage(monkeypatch) -> None:
    monkeypatch.setattr(quota_mod, "get_settings", lambda: _settings())
    limits = resolve_limits({"gateway": {"quota": {"requests_per_day": "oops"}}})
    assert limits.requests_per_day == 0


# ---- QuotaStatus remaining --------------------------------------------------


def test_status_remaining_none_when_unlimited() -> None:
    st = QuotaStatus(allowed=True, limits=QuotaLimits(0, 0), usage=QuotaUsage(5, 5))
    assert st.requests_remaining is None
    assert st.tokens_remaining is None


def test_status_remaining_floors_at_zero() -> None:
    st = QuotaStatus(allowed=False, limits=QuotaLimits(10, 100), usage=QuotaUsage(12, 250))
    assert st.requests_remaining == 0
    assert st.tokens_remaining == 0


# ---- QuotaService decision (DB stubbed) ------------------------------------


def _service_with(monkeypatch, *, limits: QuotaLimits, usage: QuotaUsage, settings=None):
    svc = QuotaService()
    monkeypatch.setattr(quota_mod, "get_settings", lambda: settings or _settings())

    async def _limits(_tenant_id):
        return limits

    async def _usage(_tenant_id):
        return usage

    monkeypatch.setattr(svc, "_resolve_tenant_limits", _limits)
    monkeypatch.setattr(svc, "_window_usage", _usage)
    return svc


async def test_check_allows_when_no_caps(monkeypatch) -> None:
    svc = _service_with(monkeypatch, limits=QuotaLimits(0, 0), usage=QuotaUsage(999, 999))
    st = await svc.check(_ctx())
    assert st.allowed is True


async def test_check_allows_under_cap(monkeypatch) -> None:
    svc = _service_with(monkeypatch, limits=QuotaLimits(10, 1000), usage=QuotaUsage(3, 200))
    st = await svc.check(_ctx())
    assert st.allowed is True
    assert st.requests_remaining == 7


async def test_check_denies_over_request_cap(monkeypatch) -> None:
    svc = _service_with(monkeypatch, limits=QuotaLimits(10, 0), usage=QuotaUsage(10, 0))
    st = await svc.check(_ctx())
    assert st.allowed is False
    assert "requests" in (st.reason or "")


async def test_check_denies_over_token_cap(monkeypatch) -> None:
    svc = _service_with(monkeypatch, limits=QuotaLimits(0, 100), usage=QuotaUsage(1, 100))
    st = await svc.check(_ctx())
    assert st.allowed is False
    assert "tokens" in (st.reason or "")


async def test_gateway_disabled_bypasses(monkeypatch) -> None:
    svc = _service_with(
        monkeypatch,
        limits=QuotaLimits(1, 1),
        usage=QuotaUsage(999, 999),
        settings=_settings(gateway_enabled=False),
    )
    st = await svc.check(_ctx())
    assert st.allowed is True


async def test_enforce_raises_quota_exceeded(monkeypatch) -> None:
    svc = _service_with(monkeypatch, limits=QuotaLimits(5, 0), usage=QuotaUsage(5, 0))
    with pytest.raises(QuotaExceeded) as ei:
        await svc.enforce(_ctx())
    assert ei.value.limit_kind == "requests"
    assert ei.value.limit == 5
    assert ei.value.used == 5


async def test_enforce_returns_status_when_allowed(monkeypatch) -> None:
    svc = _service_with(monkeypatch, limits=QuotaLimits(5, 0), usage=QuotaUsage(1, 0))
    st = await svc.enforce(_ctx())
    assert st.allowed is True
    assert st.requests_remaining == 4
