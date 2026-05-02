"""Search & RAG — hybrid retrieval + rerank."""

from faastlab_askai_search.retrievers.base import RetrievedChunk, Retriever
from faastlab_askai_search.service import SearchService

__all__ = ["RetrievedChunk", "Retriever", "SearchService"]

__version__ = "0.1.0"
