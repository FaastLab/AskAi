"""Unit tests for the gateway usage summary aggregation (read-only #4 view)."""

from __future__ import annotations

from faastlab_askai_api.routes.gateway import summarize_usage
from faastlab_askai_core.gateway import QuotaLimits, QuotaStatus, QuotaUsage


def _quota(req: int = 0, tok: int = 0, used_req: int = 0, used_tok: int = 0) -> QuotaStatus:
    return QuotaStatus(
        allowed=True,
        limits=QuotaLimits(requests_per_day=req, tokens_per_day=tok),
        usage=QuotaUsage(requests=used_req, tokens=used_tok),
    )


def test_summary_counts_by_status() -> None:
    rows = [
        ("chat", "ok", 100, 0.0),
        ("chat", "error", 0, 0.0),
        ("chat", "quota_denied", 0, 0.0),
        ("search", "ok", 20, 0.0),
    ]
    s = summarize_usage(24, rows, _quota())
    assert s.ok == 2
    assert s.errors == 1
    assert s.denied == 1
    assert s.requests == 3  # ok + error, not denied
    assert s.tokens == 120  # denied rows contribute 0
    assert s.by_purpose == {"chat": 3, "search": 1}


def test_summary_sums_cost() -> None:
    rows = [("chat", "ok", 1000, 0.002), ("chat", "ok", 500, 0.001)]
    s = summarize_usage(24, rows, _quota())
    assert s.cost_usd == 0.003
    assert s.tokens == 1500


def test_summary_empty() -> None:
    s = summarize_usage(24, [], _quota())
    assert s.requests == 0 and s.ok == 0 and s.denied == 0
    assert s.tokens == 0 and s.cost_usd == 0.0
    assert s.by_purpose == {}


def test_summary_quota_unlimited_shows_none_remaining() -> None:
    s = summarize_usage(24, [], _quota())  # 0 = unlimited
    assert s.quota.requests_remaining is None
    assert s.quota.tokens_remaining is None


def test_summary_quota_limited_shows_remaining() -> None:
    s = summarize_usage(24, [], _quota(req=500, tok=1_000_000, used_req=20, used_tok=5000))
    assert s.quota.requests_per_day == 500
    assert s.quota.requests_remaining == 480
    assert s.quota.tokens_remaining == 995_000
