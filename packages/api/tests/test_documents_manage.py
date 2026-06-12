"""Unit tests for document-management folder normalisation (pure, no DB)."""

from __future__ import annotations

from faastlab_askai_api.routes.documents import normalize_folder


def test_root_variants_become_none() -> None:
    assert normalize_folder(None) is None
    assert normalize_folder("") is None
    assert normalize_folder("   ") is None
    assert normalize_folder("/") is None
    assert normalize_folder("///") is None


def test_strips_leading_trailing_slashes() -> None:
    assert normalize_folder("/contracts/") == "contracts"
    assert normalize_folder("contracts") == "contracts"


def test_collapses_repeated_slashes_and_trims_segments() -> None:
    assert normalize_folder("contracts//2026") == "contracts/2026"
    assert normalize_folder(" contracts / 2026 ") == "contracts/2026"


def test_backslashes_treated_as_separators() -> None:
    assert normalize_folder("contracts\\2026") == "contracts/2026"


def test_traversal_segments_dropped() -> None:
    # No path can escape upward — '.' and '..' are removed.
    assert normalize_folder("../../etc") == "etc"
    assert normalize_folder("a/../b") == "a/b"
    assert normalize_folder("./a") == "a"


def test_length_capped() -> None:
    long = "x" * 500
    out = normalize_folder(long)
    assert out is not None and len(out) <= 256
