"""Pure-Python parser for FOS search-result HTML pages.

Lives in its own module (no DB / pipeline imports) so it can be
unit-tested without the full AskAi workspace installed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

FOS_BASE = "https://www.financial-ombudsman.org.uk"

DRN_RE = re.compile(r"DRN[-_]?(\d{4,8})", re.IGNORECASE)
DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y")


@dataclass
class FosDecision:
    """One row from the FOS search results."""

    drn: str
    decision_url: str
    pdf_url: str
    business: str | None = None
    product: str | None = None
    outcome: str | None = None
    date_published: date | None = None
    title: str = field(default="")

    def metadata_dict(self) -> dict[str, str | None]:
        return {
            "fos_drn": self.drn,
            "fos_business": self.business,
            "fos_product": self.product,
            "fos_outcome": (self.outcome or "").lower() or None,
            "fos_date": self.date_published.isoformat() if self.date_published else None,
            "fos_url": self.decision_url,
        }


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    cleaned = text.strip().rstrip(".,")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _extract_outcome(text: str) -> str | None:
    low = text.lower()
    # Order matters — "partially upheld" must beat "upheld".
    if "partially upheld" in low:
        return "partially upheld"
    if "not upheld" in low:
        return "not upheld"
    if "upheld" in low:
        return "upheld"
    return None


def _absolute(href: str) -> str:
    return urljoin(FOS_BASE, href)


def _parse_search_page(html: str) -> list[FosDecision]:
    """Parse one search-results HTML page → list of decisions.

    Defensive: tries multiple selectors because FOS templates have
    historically been tweaked without notice. Logs which selector
    worked so we can tighten this over time.
    """
    soup = BeautifulSoup(html, "lxml")

    # Strategy 1: explicit result-card class (current FOS template).
    cards = soup.select(
        "li.search-result, article.search-result, "
        "div.search-result, .decision-result, .results-list li"
    )

    # Strategy 2: any anchor whose href contains /decision/DRN- (fallback).
    if not cards:
        log.info("FOS parse: no cards matched — falling back to anchor scan")
        cards = []
        for a in soup.find_all("a", href=True):
            if "/decision/" in a["href"] and DRN_RE.search(a["href"]):
                cards.append(a.find_parent(["li", "article", "div", "p"]) or a)

    decisions: list[FosDecision] = []
    seen: set[str] = set()
    for card in cards:
        text = card.get_text(" ", strip=True)
        drn_match = DRN_RE.search(text)
        if not drn_match and hasattr(card, "find_all"):
            for a in card.find_all("a", href=True):
                drn_match = DRN_RE.search(a["href"])
                if drn_match:
                    break
        if not drn_match:
            continue

        drn_id = drn_match.group(1)
        drn = f"DRN-{drn_id}"
        if drn in seen:
            continue
        seen.add(drn)

        decision_anchor = None
        if hasattr(card, "find_all"):
            for a in card.find_all("a", href=True):
                if "/decision/" in a["href"] and drn_id in a["href"]:
                    decision_anchor = a
                    break
        decision_url = (
            _absolute(decision_anchor["href"])
            if decision_anchor
            else f"{FOS_BASE}/decision/{drn}"
        )
        pdf_url = f"{FOS_BASE}/decision/{drn}.pdf"

        # Optional metadata — best-effort across known class names.
        business = None
        product = None
        date_pub = None
        for label_class in ("business", "respondent", "company", "result-business"):
            el = card.select_one(f".{label_class}, [data-{label_class}]")
            if el:
                business = el.get_text(" ", strip=True)
                break
        for label_class in ("product", "category", "result-product"):
            el = card.select_one(f".{label_class}, [data-{label_class}]")
            if el:
                product = el.get_text(" ", strip=True)
                break
        for label_class in ("date", "result-date", "published"):
            el = card.select_one(f".{label_class}, [data-{label_class}], time")
            if el:
                date_pub = _parse_date(el.get("datetime") or el.get_text(strip=True))
                if date_pub:
                    break

        if not date_pub:
            for token in re.findall(r"\d{1,2}\s+\w+\s+\d{4}", text):
                date_pub = _parse_date(token)
                if date_pub:
                    break

        title = decision_anchor.get_text(" ", strip=True) if decision_anchor else drn

        decisions.append(
            FosDecision(
                drn=drn,
                decision_url=decision_url,
                pdf_url=pdf_url,
                business=business,
                product=product,
                outcome=_extract_outcome(text),
                date_published=date_pub,
                title=title or drn,
            )
        )

    return decisions
