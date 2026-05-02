"""Detect superseded regulatory documents.

Heuristics — applied at ingestion time. None alone is conclusive; the
pipeline marks a document `is_active=False` if any high-confidence
signal fires.

Signals:
1. Strong text markers in the first ~3 chunks: "this document was
   superseded on", "superseded version", "no longer current".
2. URL pattern: BoE often serves superseded versions under a
   `/archive/` or `/superseded/` path segment.

Returns the inferred supersession date when one is parseable from the
text, otherwise just a boolean flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from faastlab_askai_indexing.parsers.base import ParsedDocument

_SUPERSEDED_PHRASES = (
    "this document was superseded",
    "this document has been superseded",
    "superseded version",
    "no longer current",
    "no longer in force",
    "superseded by",
)

_DATE_RE = re.compile(
    r"(?P<day>\d{1,2})\s+"
    r"(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+"
    r"(?P<year>\d{4})",
    re.IGNORECASE,
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}


@dataclass(slots=True)
class SupersessionResult:
    is_superseded: bool
    superseded_at: datetime | None
    reason: str | None = None


def detect(doc: ParsedDocument, *, source_uri: str | None = None) -> SupersessionResult:
    """Return whether `doc` looks superseded, and an inferred date if any."""
    if source_uri:
        lower = source_uri.lower()
        if "/archive/" in lower or "/superseded/" in lower or "supersed" in lower:
            return SupersessionResult(
                is_superseded=True,
                superseded_at=None,
                reason=f"url pattern: {source_uri}",
            )

    # Scan first 3 blocks (~ first page or two).
    for block in doc.blocks[:6]:
        text = block.text.lower()
        if not any(phrase in text for phrase in _SUPERSEDED_PHRASES):
            continue
        date = _extract_date(block.text)
        return SupersessionResult(
            is_superseded=True,
            superseded_at=date,
            reason=f"text marker on page {block.page_number}",
        )

    return SupersessionResult(is_superseded=False, superseded_at=None)


def _extract_date(text: str) -> datetime | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    try:
        return datetime(
            year=int(match.group("year")),
            month=_MONTHS[match.group("month").lower()],
            day=int(match.group("day")),
        )
    except (KeyError, ValueError):
        return None
