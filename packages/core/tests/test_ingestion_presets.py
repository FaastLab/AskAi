"""Regulator presets — well-formed, real URLs, licensed (pure, no DB)."""

from __future__ import annotations

from faastlab_askai_core.ingestion import find_preset, regulator_presets
from faastlab_askai_core.ingestion.defaults import REGULATOR_CATEGORIES, SOURCE_KINDS


def test_ships_the_key_regulators() -> None:
    cats = {p["category"] for p in regulator_presets()}
    assert {"fca", "pra", "boe", "hmrc", "ico"} <= cats


def test_every_preset_is_well_formed() -> None:
    for p in regulator_presets():
        assert p["key"] and p["name"] and p["description"]
        assert p["category"] in REGULATOR_CATEGORIES
        assert p["kind"] in SOURCE_KINDS
        assert p["license"]  # licensing is mandatory (design §10)
        urls = p["config"].get("start_urls") or []
        assert urls, f"{p['key']} has no start URLs"
        assert all(u.startswith("https://") for u in urls)


def test_keys_unique() -> None:
    keys = [p["key"] for p in regulator_presets()]
    assert len(keys) == len(set(keys))


def test_fca_has_many_sourcebooks() -> None:
    fca = find_preset("fca-handbook")
    assert fca is not None
    # The full handbook is dozens of sourcebooks, not just a contents page.
    assert len(fca["config"]["start_urls"]) >= 20


def test_hmrc_crawls_child_pages() -> None:
    # The known gap: HMRC manuals were ingested as index pages only. The preset
    # must crawl (follow child rule-pages), bounded to the manuals path.
    hmrc = find_preset("hmrc-manuals")
    assert hmrc is not None
    assert hmrc["config"]["mode"] == "crawl"
    assert "hmrc-internal-manuals" in hmrc["config"]["url_prefix"]
    assert hmrc["config"]["max_pages"] >= 100


def test_find_preset_unknown() -> None:
    assert find_preset("nope") is None
