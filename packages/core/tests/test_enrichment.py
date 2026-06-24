"""Unit tests for the per-tenant enrichment preference (pure, no DB)."""

from __future__ import annotations

from faastlab_askai_core.enrichment import enrichment_enabled, with_enrichment


def test_falls_back_to_default_when_unset() -> None:
    assert enrichment_enabled(None, default=True) is True
    assert enrichment_enabled({}, default=False) is False
    assert enrichment_enabled({"enrichment": {}}, default=True) is True


def test_tenant_choice_overrides_default() -> None:
    on = {"enrichment": {"auto": True}}
    off = {"enrichment": {"auto": False}}
    assert enrichment_enabled(on, default=False) is True
    assert enrichment_enabled(off, default=True) is False


def test_non_bool_value_ignored() -> None:
    # A junk value falls back to the default rather than coercing.
    assert enrichment_enabled({"enrichment": {"auto": "yes"}}, default=True) is True


def test_with_enrichment_sets_flag_without_clobbering_other_settings() -> None:
    settings = {"gateway": {"policy": {"enabled": True}}}
    out = with_enrichment(settings, auto=True)
    assert out["enrichment"]["auto"] is True
    # Other settings preserved; input not mutated.
    assert out["gateway"] == {"policy": {"enabled": True}}
    assert "enrichment" not in settings


def test_with_enrichment_round_trips() -> None:
    out = with_enrichment(None, auto=True)
    assert enrichment_enabled(out, default=False) is True
    out = with_enrichment(out, auto=False)
    assert enrichment_enabled(out, default=True) is False
