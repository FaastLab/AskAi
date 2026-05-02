"""FaastLab AskAi — Python SDK.

Sync and async clients over the REST API. Streaming via SSE for /v1/ask.

    >>> from faastlab_askai_sdk import AskAiClient
    >>> client = AskAiClient(base_url="http://localhost:8000", api_key="…")
    >>> hits = client.search("capital requirements", k=5)
    >>> answer = client.ask("Summarise FCA's stance on consumer duty")
    >>> for token in client.stream_ask("How has X changed since 2022?"):
    ...     print(token, end="")

Async equivalents live on `AsyncAskAiClient`.
"""

from faastlab_askai_sdk.client import AskAiClient, AsyncAskAiClient
from faastlab_askai_sdk.models import (
    AskResult,
    Citation,
    DocumentRecord,
    SearchHit,
    SearchResult,
)

__all__ = [
    "AskAiClient",
    "AskResult",
    "AsyncAskAiClient",
    "Citation",
    "DocumentRecord",
    "SearchHit",
    "SearchResult",
]
__version__ = "0.1.0"
