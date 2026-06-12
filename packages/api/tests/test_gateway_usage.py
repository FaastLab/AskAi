"""Unit tests for the gateway usage summary aggregation (read-only #4 view)."""

from __future__ import annotations

from faastlab_askai_api.routes.gateway import (
    _percentile,
    compute_request_stats,
    summarize_usage,
)
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


# ---- #5 observability: latency stats ---------------------------------------


def test_percentile_empty_is_none() -> None:
    assert _percentile([], 0.5) is None


def test_percentile_single() -> None:
    assert _percentile([42.0], 0.95) == 42.0


def test_percentile_median_and_p95() -> None:
    vals = [float(x) for x in range(1, 101)]  # 1..100
    assert _percentile(vals, 0.50) == 50.5
    assert _percentile(vals, 0.95) == 95.05


def test_request_stats_excludes_denied() -> None:
    rows = [
        ("ok", 100.0),
        ("ok", 300.0),
        ("error", 200.0),
        ("quota_denied", None),  # excluded from count + latency
    ]
    stats = compute_request_stats(rows)
    assert stats.count == 3  # denied excluded
    assert stats.error_rate == round(1 / 3, 4)
    assert stats.p50_ms == 200.0  # median of [100,200,300]


def test_request_stats_empty() -> None:
    stats = compute_request_stats([])
    assert stats.count == 0
    assert stats.p50_ms is None and stats.p95_ms is None
    assert stats.error_rate == 0.0


def test_request_stats_ignores_missing_latency() -> None:
    rows = [("ok", None), ("ok", 50.0)]
    stats = compute_request_stats(rows)
    assert stats.count == 2  # both count as attempts
    assert stats.p50_ms == 50.0  # only the non-null latency is measured
