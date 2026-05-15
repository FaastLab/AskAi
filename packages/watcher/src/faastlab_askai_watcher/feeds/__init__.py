"""Feed adapters — one source per regulator (RSS or HTML scrape)."""

from faastlab_askai_watcher.feeds.base import FeedSource, PublicationEvent
from faastlab_askai_watcher.feeds.registry import default_feeds, feed_for
from faastlab_askai_watcher.feeds.rss import RssFeed

__all__ = ["FeedSource", "PublicationEvent", "RssFeed", "default_feeds", "feed_for"]
