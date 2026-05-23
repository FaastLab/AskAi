"""Preconfigured feed registry — the five UK regulators we ship with.

URLs are tunable via env vars (`WATCHER_FCA_URL`, etc.) so we can swap
without a code change when a regulator moves a feed. The defaults below
were the working URLs at time of writing; if a regulator stops serving
RSS, swap the line to a scrape-based subclass.
"""

from __future__ import annotations

from collections.abc import Iterable

from faastlab_askai_core.config import get_settings

from faastlab_askai_watcher.feeds.base import FeedSource
from faastlab_askai_watcher.feeds.rss import RssFeed

# Codes are short, lowercase, stable — used as a primary-key fragment in
# `watcher_events` so renaming one is a migration, not a refactor.
SUPPORTED_REGULATORS: tuple[str, ...] = (
    "fca", "boe", "pra", "fos", "tpr", "ico", "hmrc",
)

# gov.uk firehose paths that look regulatory but aren't useful corpus content.
# Applied to feeds whose source is `gov.uk/government/organisations/...atom`
# (HMRC/TPR/ICO). Keeps the corpus clean — statistics announcements, ministerial
# speeches and press releases were poisoning retrieval with empty/duplicate hits.
GOVUK_NOISE_PATHS: tuple[str, ...] = (
    "/government/statistics/",          # incl. /announcements/
    "/government/news/",
    "/government/speeches/",
    "/government/people/",
    "/government/ministers/",
    "/government/case-studies/",
    "/government/world-location-news/",
    "/government/collections/",         # index pages, no body content
    "/government/topical-events/",
    "/government/foi-releases/",
    "/government/correspondence/",      # press lines, not guidance
)


def default_feeds() -> list[FeedSource]:
    """Return the watcher's default feed set, configured from settings.

    Feeds whose URL is blank are skipped — used when a regulator doesn't
    publish a usable RSS endpoint (currently FOS). A future scrape-based
    adapter can replace these without touching the orchestrator.
    """
    s = get_settings()
    ua = s.watcher_user_agent
    # Apply the gov.uk noise blocklist to feeds sourced from
    # gov.uk/government/organisations/*.atom. FCA/BoE/PRA have their own
    # editorial feeds so they don't need it.
    govuk_excludes = {"exclude_url_substrings": GOVUK_NOISE_PATHS}
    candidates: list[tuple[str, str, dict]] = [
        ("fca",  s.watcher_fca_url,  {}),
        ("boe",  s.watcher_boe_url,  {}),
        ("pra",  s.watcher_pra_url,  {"event_type": "prudential-publication"}),
        ("fos",  s.watcher_fos_url,  {}),
        ("tpr",  s.watcher_tpr_url,  govuk_excludes),
        ("ico",  s.watcher_ico_url,  govuk_excludes),
        ("hmrc", s.watcher_hmrc_url, govuk_excludes),
    ]
    return [
        RssFeed(reg, url, user_agent=ua, **kwargs)
        for reg, url, kwargs in candidates
        if url and url.strip()
    ]


def feed_for(regulator: str) -> FeedSource | None:
    """Return the configured feed for a regulator code, or None if unknown."""
    regulator = regulator.lower().strip()
    for f in default_feeds():
        if f.regulator == regulator:
            return f
    return None


def filter_feeds(
    feeds: Iterable[FeedSource], *, only: list[str] | None
) -> list[FeedSource]:
    """Optionally narrow a feed list to a subset of regulator codes."""
    if not only:
        return list(feeds)
    wanted = {r.lower().strip() for r in only}
    return [f for f in feeds if f.regulator in wanted]
