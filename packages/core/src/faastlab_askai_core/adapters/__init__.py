"""Adapter Protocols.

Every external dependency (LLM, embeddings, vector store, storage, queue,
auth) is described here as a `typing.Protocol`. Concrete implementations
live in sibling packages and are wired up by `core.factory`.

Application code MUST depend on these Protocols, never on concrete
implementations directly.
"""

from faastlab_askai_core.adapters.auth import AuthAdapter, Principal
from faastlab_askai_core.adapters.embeddings import EmbeddingsAdapter
from faastlab_askai_core.adapters.llm import LLMAdapter, LLMMessage
from faastlab_askai_core.adapters.queue import QueueAdapter
from faastlab_askai_core.adapters.storage import StorageAdapter
from faastlab_askai_core.adapters.vector import VectorHit, VectorStoreAdapter

__all__ = [
    "AuthAdapter",
    "EmbeddingsAdapter",
    "LLMAdapter",
    "LLMMessage",
    "Principal",
    "QueueAdapter",
    "StorageAdapter",
    "VectorHit",
    "VectorStoreAdapter",
]
