"""POST /v1/search — hybrid retrieval with rerank, scoped to caller's tenant."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.quota import enforce_quota
from faastlab_askai_api.middleware.trial import require_active_trial_or_subscription
from faastlab_askai_api.routes.ask import _require_byok_if_configured
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.config import get_settings
from faastlab_askai_core.gateway import (
    GatewayContext,
    record_usage,
    usage_from_text,
)
from faastlab_askai_core.schemas.chunk import ChunkWithScore
from faastlab_askai_core.schemas.search import SearchRequest, SearchResult
from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.service import SearchService

router = APIRouter(tags=["search"])
_service = SearchService()


@router.post("/search", response_model=SearchResult)
async def search(
    body: SearchRequest,
    request: Request,
    principal: Principal = Depends(require_active_trial_or_subscription),
    _quota: Principal = Depends(enforce_quota("search")),
) -> SearchResult:
    _require_byok_if_configured()
    filters = _build_filters(body.filters)
    outcome = await _service.search(
        tenant_id=principal.tenant_id,
        query=body.query,
        k=body.k,
        filters=filters,
    )

    # Ledger the query-embedding spend so search counts toward request quota.
    settings = get_settings()
    await record_usage(
        GatewayContext(
            tenant_id=principal.tenant_id,
            tenant_slug=principal.tenant_slug,
            user_id=principal.user_id,
            purpose="search",
            request_id=request.headers.get("x-request-id"),
        ),
        usage_from_text(
            prompt=body.query,
            completion="",
            provider=settings.embeddings_provider,
            model=settings.embeddings_model,
            latency_ms=outcome.latency_ms,
        ),
    )

    await record_action(
        principal=principal,
        action="search",
        resource="/v1/search",
        query=body.query,
        response_summary=f"{len(outcome.hits)} hits returned",
        sources=[
            {
                "document_id": str(h.document_id),
                "chunk_id": str(h.chunk_id),
                "section_path": h.section_path,
                "page_number": h.page_number,
                "score": round(h.score, 3),
            }
            for h in outcome.hits[:10]
        ],
        latency_ms=outcome.latency_ms,
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
