"""Smoke tests for the FOS search-page parser.

These are pure parser tests — no live HTTP — so they never flake on
FOS being slow or rate-limiting CI. The two HTML snippets below mimic
the two real-world templates we've observed on the FOS site:

  1. Structured `<li class="search-result">` cards with named
     sub-elements (the "happy path").
  2. Loosely-formatted markup with no result classes, where we have
     to fall back to scanning for /decision/DRN- anchors.

If FOS changes their template and breaks both, this test will fail
loudly and we'll know to update the parser before the ingester
silently starts producing zero decisions per page.
"""

from __future__ import annotations

import pytest

from corpus.uk_finreg.fos_parser import (
    FosDecision,
    _extract_outcome,
    _parse_date,
    _parse_search_page,
)


STRUCTURED_HTML = """
<html><body>
<ul class="results-list">
  <li class="search-result">
    <a href="/decision/DRN-5012345">DRN-5012345 — Decision summary</a>
    <span class="business">Acme Credit Ltd</span>
    <span class="product">Credit cards</span>
    <time class="date" datetime="2025-03-14">14 March 2025</time>
    <p>The complaint is upheld.</p>
  </li>
  <li class="search-result">
    <a href="/decision/DRN-6011111">DRN-6011111 — Decision summary</a>
    <span class="business">Beta Mortgages plc</span>
    <span class="product">Mortgages</span>
    <time class="date" datetime="2025-04-02">02 April 2025</time>
    <p>The complaint is not upheld.</p>
  </li>
  <li class="search-result">
    <a href="/decision/DRN-7022222">DRN-7022222 — Decision summary</a>
    <span class="business">Gamma Loans Ltd</span>
    <span class="product">Personal loans</span>
    <time class="date" datetime="2025-04-10">10 April 2025</time>
    <p>The complaint is partially upheld.</p>
  </li>
</ul>
</body></html>
"""


LOOSE_HTML = """
<html><body>
<div>
  <p><a href="/decision/DRN-9999999">Loose decision</a> — issued 5 May 2025, upheld</p>
  <p><a href="/decision/DRN-8888888">Another</a> — issued 6 May 2025, not upheld</p>
</div>
</body></html>
"""


def test_parses_structured_search_page() -> None:
    decisions = _parse_search_page(STRUCTURED_HTML)
    assert len(decisions) == 3
    by_drn = {d.drn: d for d in decisions}

    d1 = by_drn["DRN-5012345"]
    assert isinstance(d1, FosDecision)
    assert d1.business == "Acme Credit Ltd"
    assert d1.product == "Credit cards"
    assert d1.outcome == "upheld"
    assert d1.date_published is not None
    assert d1.date_published.isoformat() == "2025-03-14"
    assert d1.pdf_url == "https://www.financial-ombudsman.org.uk/decision/DRN-5012345.pdf"

    assert by_drn["DRN-6011111"].outcome == "not upheld"
    assert by_drn["DRN-7022222"].outcome == "partially upheld"


def test_loose_template_falls_back_to_anchor_scan() -> None:
    decisions = _parse_search_page(LOOSE_HTML)
    drns = sorted(d.drn for d in decisions)
    assert drns == ["DRN-8888888", "DRN-9999999"]
    # We still get an outcome from the surrounding text even without
    # a structured outcome element.
    by_drn = {d.drn: d for d in decisions}
    assert by_drn["DRN-9999999"].outcome == "upheld"
    assert by_drn["DRN-8888888"].outcome == "not upheld"


def test_extract_outcome_priority() -> None:
    # "partially upheld" must win over plain "upheld" substring.
    assert _extract_outcome("The complaint is partially upheld.") == "partially upheld"
    assert _extract_outcome("The complaint is not upheld.") == "not upheld"
    assert _extract_outcome("The complaint is upheld.") == "upheld"
    assert _extract_outcome("Withdrawn before resolution") is None


@pytest.mark.parametrize(
    "text,expected_iso",
    [
        ("14 March 2025", "2025-03-14"),
        ("02 Apr 2025", "2025-04-02"),
        ("2025-04-10", "2025-04-10"),
        ("10/04/2025", "2025-04-10"),
    ],
)
def test_parse_date_formats(text: str, expected_iso: str) -> None:
    d = _parse_date(text)
    assert d is not None
    assert d.isoformat() == expected_iso


def test_parse_date_handles_garbage() -> None:
    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("not a date") is None


def test_metadata_dict_strips_none_values_at_call_site() -> None:
    d = FosDecision(
        drn="DRN-1",
        decision_url="https://x/y",
        pdf_url="https://x/y.pdf",
        business=None,
        outcome="upheld",
    )
    meta = d.metadata_dict()
    # The dataclass returns all keys (with None where unset); the
    # ingester is the one that filters Nones before persisting.
    assert meta["fos_drn"] == "DRN-1"
    assert meta["fos_outcome"] == "upheld"
    assert meta["fos_business"] is None
    assert meta["fos_date"] is None
