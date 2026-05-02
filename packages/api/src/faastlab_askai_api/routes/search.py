"""POST /v1/search — hybrid retrieval with rerank, scoped to caller's tenant."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.schemas.search import SearchRequest, SearchResult
from faastlab_askai_core.schemas.chunk import ChunkWithScore
from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.service import SearchService

from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_api.routes.ask import _require_byok_if_configured

router = APIRouter(tags=["search"])
_service = SearchService()


@router.post("/search", response_model=SearchResult)
async def search(
    body: SearchRequest,
    principal: Principal = Depends(get_principal),
) -> SearchResult:
    _require_byok_if_configured()
    filters = _build_filters(body.filters)
    outcome = await _service.search(
        tenant_id=principal.tenant_id,
        query=body.query,
        k=body.k,
        filters=filters,
    )
    return SearchResult(
        query=outcome.query,
        latency_ms=outcome.latency_ms,
        hits=[
            ChunkWithScore(
                id=h.chunk_id,
                document_id=h.document_id,
                tenant_id=h.tenant_id,
                content=h.content,
                section_path=h.section_path,
                page_number=h.page_number,
                char_start=h.char_start,
                char_end=h.char_end,
                metadata=h.metadata,
                score=h.score,
                rank=h.rank,
            )
            for h in outcome.hits
        ],
    )


def _build_filters(raw: dict[str, object]) -> SearchFilters:
    filters = SearchFilters()
    if "doc_types" in raw:
        filters.doc_types = list(raw["doc_types"])  # type: ignore[arg-type]
    if "only_active" in raw:
        filters.only_active = bool(raw["only_active"])
    if "metadata" in raw:
        filters.metadata = {str(k): str(v) for k, v in (raw["metadata"] or {}).items()}  # type: ignore[union-attr]
    return filters
