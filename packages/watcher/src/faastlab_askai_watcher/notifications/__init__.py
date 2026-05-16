"""Notification adapters — console / DB always-on, webhook + ingest opt-in."""

from faastlab_askai_watcher.notifications.base import Notifier
from faastlab_askai_watcher.notifications.console import ConsoleNotifier
from faastlab_askai_watcher.notifications.db import DBNotifier
from faastlab_askai_watcher.notifications.ingest import IngestNotifier
from faastlab_askai_watcher.notifications.webhook import WebhookNotifier

__all__ = [
    "ConsoleNotifier",
    "DBNotifier",
    "IngestNotifier",
    "Notifier",
    "WebhookNotifier",
]
