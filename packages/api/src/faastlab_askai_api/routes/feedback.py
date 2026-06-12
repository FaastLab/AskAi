"""POST /v1/feedback — record a user's reaction to an answer (#7 feedback loop).

A thumbs up/down (and optional free-text correction) on a `/v1/ask` answer.
The reaction is anchored to the answer's `request_id` and carries the cited
document/chunk ids, so the retrieval layer can later attribute the signal to
the documents that produced the answer and nudge ranking accordingly (see
`faastlab_askai_search.feedback`).

Any authenticated tenant member may submit feedback — it's their own corpus
they're improving. The write is best-effort from the user's point of view but
audited so the governance feed shows who corrected what.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.principal import get_principal
from faastlab_askai_core.adapters import Principal
from faastlab_askai_core.db import AnswerFeedback, get_sessionmaker
from faastlab_askai_search.feedback import normalize_query

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    rating: int = Field(description="+1 = helpful, -1 = not helpful")
    query: str = Field(default="", max_length=4000)
    request_id: str | None = Field(default=None, max_length=64)
    session_id: UUID | None = None
    correction: str | None = Field(default=None, max_length=8000)
    document_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)


class FeedbackResponse(BaseModel):
    status: str
    id: int


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    body: FeedbackRequest,
    principal: Principal = Depends(get_principal),
) -> FeedbackResponse:
    # Normalise the rating to exactly +1 / -1 — the signal is a vote, not a
    # magnitude, so a client sending 5 or -3 still counts as one up/down vote.
    rating = 1 if body.rating >= 0 else -1
    row = AnswerFeedback(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        session_id=body.session_id,
        request_id=body.request_id,
        query=body.query,
        normalized_query=normalize_query(body.query),
        rating=rating,
        correction=(body.correction or None),
        document_ids=[str(d) for d in body.document_ids],
        chunk_ids=[str(c) for c in body.chunk_ids],
    )
    sm = get_sessionmaker()
    async with sm() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        feedback_id = row.id

    await record_action(
        principal=principal,
        action="feedback.submit",
        resource="/v1/feedback",
        query=body.query or None,
        extra={
            "rating": rating,
            "request_id": body.request_id,
            "has_correction": bool(body.correction),
            "document_ids": [str(d) for d in body.document_ids][:20],
        },
    )
    return FeedbackResponse(status="ok", id=feedback_id)
