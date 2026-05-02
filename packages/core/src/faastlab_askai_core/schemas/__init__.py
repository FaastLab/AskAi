"""Pydantic schemas — wire-format DTOs for API, MCP, SDK."""

from faastlab_askai_core.schemas.chunk import ChunkRead, ChunkWithScore
from faastlab_askai_core.schemas.document import (
    DocumentCreate,
    DocumentRead,
    DocumentSummary,
    DocumentUpdate,
)
from faastlab_askai_core.schemas.search import AskRequest, AskResponse, SearchRequest, SearchResult
from faastlab_askai_core.schemas.tenant import TenantCreate, TenantRead

__all__ = [
    "AskRequest",
    "AskResponse",
    "ChunkRead",
    "ChunkWithScore",
    "DocumentCreate",
    "DocumentRead",
    "DocumentSummary",
    "DocumentUpdate",
    "SearchRequest",
    "SearchResult",
    "TenantCreate",
    "TenantRead",
]
