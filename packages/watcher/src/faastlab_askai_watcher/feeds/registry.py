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


def default_feeds() -> list[FeedSource]:
    """Return the watcher's default feed set, configured from settings."""
    s = get_settings()
    ua = s.watcher_user_agent
    return [
        RssFeed("fca", s.watcher_fca_url, user_agent=ua),
        RssFeed("boe", s.watcher_boe_url, user_agent=ua),
        RssFeed("pra", s.watcher_pra_url, user_agent=ua, event_type="prudential-publication"),
        RssFeed("fos", s.watcher_fos_url, user_agent=ua),
        RssFeed("tpr", s.watcher_tpr_url, user_agent=ua),
        RssFeed("ico", s.watcher_ico_url, user_agent=ua),
        RssFeed("hmrc", s.watcher_hmrc_url, user_agent=ua),
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
