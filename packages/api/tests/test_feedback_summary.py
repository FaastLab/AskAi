"""Unit tests for the feedback-loop summary aggregation (#7, read-only view)."""

from __future__ import annotations

from datetime import UTC, datetime

from faastlab_askai_api.routes.gateway import summarize_feedback


def _row(rating: int, correction: str | None = None, query: str = "q"):
    return (datetime.now(UTC), query, rating, correction)


def test_empty() -> None:
    s = summarize_feedback(720, [])
    assert s.up == 0 and s.down == 0 and s.corrections == 0
    assert s.helpful_rate == 0.0
    assert s.recent_corrections == []


def test_counts_up_down_and_helpful_rate() -> None:
    rows = [_row(1), _row(1), _row(1), _row(-1)]
    s = summarize_feedback(720, rows)
    assert s.up == 3 and s.down == 1
    assert s.helpful_rate == 0.75


def test_zero_rating_counts_as_up() -> None:
    # Route normalises to ±1, but the aggregator treats >=0 as up defensively.
    s = summarize_feedback(720, [_row(0)])
    assert s.up == 1 and s.down == 0


def test_corrections_collected_and_capped() -> None:
    rows = [_row(-1, correction=f"fix {i}") for i in range(30)]
    s = summarize_feedback(720, rows)
    assert s.corrections == 30
    assert len(s.recent_corrections) == 25  # capped
    assert s.recent_corrections[0].correction == "fix 0"


def test_rows_without_correction_excluded_from_list() -> None:
    rows = [_row(1), _row(-1, correction="this was wrong")]
    s = summarize_feedback(720, rows)
    assert s.corrections == 1
    assert s.recent_corrections[0].correction == "this was wrong"
