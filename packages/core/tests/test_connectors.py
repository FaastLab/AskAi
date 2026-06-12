"""Unit tests for the web-connector config model + helpers (pure, no DB)."""

from __future__ import annotations

from faastlab_askai_core.connectors import (
    MAX_MAX_DEPTH,
    MAX_MAX_PAGES,
    RUN_HISTORY_LIMIT,
    append_run,
    find_connector,
    is_due,
    list_connectors,
    normalize_connector,
    remove_connector,
    upsert_connector,
)

# ---- normalize_connector ---------------------------------------------------


def test_normalize_clamps_bounds() -> None:
    c = normalize_connector({"name": "x", "max_pages": 999999, "max_depth": 99})
    assert c["max_pages"] == MAX_MAX_PAGES
    assert c["max_depth"] == MAX_MAX_DEPTH


def test_normalize_invalid_mode_falls_back_to_crawl() -> None:
    assert normalize_connector({"mode": "wat"})["mode"] == "crawl"


def test_normalize_drops_empty_urls_and_trims() -> None:
    c = normalize_connector({"start_urls": [" https://a ", "", "  "]})
    assert c["start_urls"] == ["https://a"]


def test_normalize_interval_none_when_zero_or_missing() -> None:
    def interval(raw: dict) -> int | None:
        return normalize_connector(raw)["schedule_interval_minutes"]

    assert interval({}) is None
    assert interval({"schedule_interval_minutes": 0}) is None
    assert interval({"schedule_interval_minutes": 30}) == 30


def test_normalize_preserves_server_fields() -> None:
    c = normalize_connector({"id": "abc", "created_at": "t0", "runs": [{"x": 1}]})
    assert c["id"] == "abc" and c["created_at"] == "t0"
    assert c["runs"] == [{"x": 1}]


# ---- list / find / upsert / remove -----------------------------------------


def test_list_connectors_handles_missing_block() -> None:
    assert list_connectors(None) == []
    assert list_connectors({}) == []
    assert list_connectors({"connectors": {"items": [{"id": "a"}]}}) == [{"id": "a"}]


def test_upsert_inserts_then_replaces() -> None:
    items = upsert_connector([], {"id": "a", "name": "one"})
    assert items == [{"id": "a", "name": "one"}]
    items = upsert_connector(items, {"id": "a", "name": "two"})
    assert items == [{"id": "a", "name": "two"}]  # replaced in place, not appended


def test_remove_connector() -> None:
    items = [{"id": "a"}, {"id": "b"}]
    assert remove_connector(items, "a") == [{"id": "b"}]


def test_find_connector() -> None:
    settings = {"connectors": {"items": [{"id": "a"}, {"id": "b"}]}}
    assert find_connector(settings, "b") == {"id": "b"}
    assert find_connector(settings, "z") is None


# ---- append_run ------------------------------------------------------------


def test_append_run_prepends_and_caps() -> None:
    c: dict = {"id": "a", "runs": []}
    for i in range(RUN_HISTORY_LIMIT + 5):
        c = append_run(c, {"run_id": str(i), "finished_at": f"t{i}"})
    assert len(c["runs"]) == RUN_HISTORY_LIMIT
    # Newest first.
    assert c["runs"][0]["run_id"] == str(RUN_HISTORY_LIMIT + 4)
    assert c["last_run_at"] == f"t{RUN_HISTORY_LIMIT + 4}"


# ---- is_due ----------------------------------------------------------------


def test_is_due_disabled_or_unscheduled_never_due() -> None:
    assert is_due({"enabled": False, "schedule_interval_minutes": 10}, 1_000_000) is False
    assert is_due({"enabled": True, "schedule_interval_minutes": None}, 1_000_000) is False


def test_is_due_never_run_is_due() -> None:
    assert is_due({"enabled": True, "schedule_interval_minutes": 10}, 1_000_000) is True


def test_is_due_respects_interval() -> None:
    c = {"enabled": True, "schedule_interval_minutes": 10, "last_run_epoch": 1_000_000}
    assert is_due(c, 1_000_000 + 9 * 60) is False  # 9 min < 10 min
    assert is_due(c, 1_000_000 + 11 * 60) is True  # 11 min >= 10 min
