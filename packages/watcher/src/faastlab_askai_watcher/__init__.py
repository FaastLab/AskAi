"""FaastLab AskAi — regulator change watcher.

Polls FCA / BoE / PRA / FOS / TPR news feeds, dedupes events on
`(regulator, external_id)`, persists them to `watcher_events`, and fans
notifications to console / DB / webhook (Slack later).

See `service.WatcherService` for the orchestrator entry point, or run
`python -m faastlab_askai_watcher poll` for a one-shot CLI invocation.
"""

from faastlab_askai_watcher.feeds.base import FeedSource, PublicationEvent
from faastlab_askai_watcher.service import PollOutcome, WatcherService

__all__ = ["FeedSource", "PollOutcome", "PublicationEvent", "WatcherService"]
