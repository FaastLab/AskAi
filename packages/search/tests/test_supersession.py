"""Supersession heuristic tests."""

from __future__ import annotations

from datetime import datetime

from faastlab_askai_indexing.parsers.base import ParsedBlock, ParsedDocument
from faastlab_askai_indexing.supersession import detect


def _doc(text: str, *, page: int = 1) -> ParsedDocument:
    return ParsedDocument(
        title="Test", blocks=[ParsedBlock(text=text, page_number=page)]
    )


def test_detects_text_marker_with_date() -> None:
    doc = _doc("This document was superseded on 18 December 2020 by the new version.")
    result = detect(doc)
    assert result.is_superseded
    assert result.superseded_at == datetime(2020, 12, 18)
    assert result.reason and "page 1" in result.reason


def test_detects_url_pattern() -> None:
    doc = _doc("Some normal regulatory text.")
    result = detect(doc, source_uri="https://www.bankofengland.co.uk/archive/old-doc.pdf")
    assert result.is_superseded
    assert "url pattern" in (result.reason or "")


def test_clean_doc_is_active() -> None:
    doc = _doc("This document sets out the PRA's expectations.")
    result = detect(doc)
    assert not result.is_superseded
    assert result.superseded_at is None
