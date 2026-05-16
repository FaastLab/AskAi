"""POST /v1/ask — full RAG answer.

- `stream=false` → blocking JSON response with answer + citations.
- `stream=true`  → SSE stream with `retrieve` / `token` / `done` events.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from faastlab_askai_askai.service import AskAiService
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.byok import get_request_secrets
from faastlab_askai_core.config import get_settings
from faastlab_askai_core.schemas.search import AskRequest, AskResponse
from faastlab_askai_search.filters import SearchFilters

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_api.middleware.trial import require_active_trial_or_subscription


def _require_byok_if_configured() -> None:
    settings = get_settings()
    if not settings.require_byok:
        return
    secrets = get_request_secrets()
    if not secrets or not secrets.openai_api_key:
        raise HTTPException(
            status_code=401,
            detail=(
                "This deployment requires a bring-your-own OpenAI key. "
                "Send it as the X-OpenAI-API-Key header."
            ),
        )


router = APIRouter(tags=["ask"])
_service = AskAiService()


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    request: Request,
    principal: Principal = Depends(require_active_trial_or_subscription),
):
    _require_byok_if_configured()
    filters = SearchFilters(
        only_active=not body.filters.get("include_superseded", False)
    )
    if body.stream:
        return EventSourceResponse(
            _sse_iter(
                principal=principal,
                question=body.query,
                session_id=body.session_id,
                filters=filters,
            )
        )

    outcome = await _service.ask(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        question=body.query,
        session_id=body.session_id,
        filters=filters,
    )

    # Compliance audit: capture the question, a summary of the answer,
    # and the citations so auditors can replay what the system said.
    await record_action(
        principal=principal,
        action="ask",
        resource="/v1/ask",
        query=body.query,
        response_summary=outcome.answer[:600],
        sources=[
            {
                "document_title": c.document_title,
                "document_id": str(c.document_id),
                "chunk_id": str(c.chunk_id),
                "page_number": c.page_number,
                "section_path": c.section_path,
            }
            for c in outcome.citations
        ],
        latency_ms=outcome.total_latency_ms,
        extra={
            "confidence": outcome.confidence,
            "session_id": str(outcome.session_id),
        },
    )

    return AskResponse(
        answer=outcome.answer,
        citations=outcome.citations,
        session_id=outcome.session_id,
        latency_ms=outcome.total_latency_ms,
        generated_at=outcome.generated_at,
        confidence=outcome.confidence,
    )


async def _sse_iter(
    *,
    principal: Principal,
    question: str,
    session_id,
    filters: SearchFilters,
) -> AsyncIterator[dict[str, str]]:
    import json

    async for event in _service.stream_ask(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        question=question,
        session_id=session_id,
        filters=filters,
    ):
        yield {"event": str(event.get("event")), "data": json.dumps(event)}
