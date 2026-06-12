"""AskAiService — public entry: question → cited answer.

Orchestrates: load history → retrieve → prompt → LLM → parse citations
→ persist turn. Both blocking (`ask`) and streaming (`stream_ask`) APIs.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from faastlab_askai_askai.citations import extract_citations
from faastlab_askai_askai.memory import SessionMemory
from faastlab_askai_askai.prompts import REFUSAL_NO_CONTEXT, build_rag_messages
from faastlab_askai_core.gateway import AIGateway, GatewayContext
from faastlab_askai_core.schemas.search import Citation
from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.service import SearchOutcome, SearchService

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AskOutcome:
    answer: str
    citations: list[Citation]
    session_id: UUID
    confidence: float
    retrieval_latency_ms: float
    total_latency_ms: float
    generated_at: datetime
    chunks_used: int = 0
    debug: dict[str, object] = field(default_factory=dict)


class AskAiService:
    def __init__(
        self,
        *,
        search: SearchService | None = None,
        gateway: AIGateway | None = None,
        memory: SessionMemory | None = None,
        retrieve_k: int = 16,
        temperature: float = 0.0,
        max_tokens: int | None = 1400,
    ) -> None:
        self._search = search or SearchService()
        # Generation flows through the AI gateway: per-tenant quota + routing
        # + exact usage ledger, all at one chokepoint.
        self._gateway = gateway or AIGateway()
        self._memory = memory or SessionMemory()
        self._retrieve_k = retrieve_k
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def ask(
        self,
        *,
        tenant_id: UUID,
        user_id: str,
        question: str,
        session_id: UUID | None = None,
        filters: SearchFilters | None = None,
        rerank: bool = True,
        request_id: str | None = None,
    ) -> AskOutcome:
        started = perf_counter()
        session_uuid, history = await self._memory.load(
            tenant_id=tenant_id, session_id=session_id
        )

        retrieval = await self._do_retrieval(tenant_id, question, filters, rerank)
        retrieval_ms = retrieval.latency_ms

        ctx = GatewayContext(
            tenant_id=tenant_id, user_id=user_id, purpose="chat", request_id=request_id
        )
        if retrieval.hits:
            messages = build_rag_messages(question, retrieval.hits, history=history)
            generated = await self._gateway.complete(
                ctx,
                messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            answer_text = generated.text
        else:
            answer_text = REFUSAL_NO_CONTEXT
        citations = extract_citations(answer_text, retrieval.hits)

        total_ms = (perf_counter() - started) * 1000.0

        # Persist user/assistant turn for follow-up questions.
        await self._memory.append(
            tenant_id=tenant_id,
            session_id=session_uuid,
            user_id=user_id,
            question=question,
            answer=answer_text,
            citations=[c.model_dump(mode="json") for c in citations],
        )

        return AskOutcome(
            answer=answer_text,
            citations=citations,
            session_id=session_uuid,
            confidence=retrieval.confidence,
            retrieval_latency_ms=retrieval_ms,
            total_latency_ms=round(total_ms, 2),
            generated_at=datetime.now(UTC),
            chunks_used=len(retrieval.hits),
        )

    async def stream_ask(
        self,
        *,
        tenant_id: UUID,
        user_id: str,
        question: str,
        session_id: UUID | None = None,
        filters: SearchFilters | None = None,
        rerank: bool = True,
        request_id: str | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        """Yield JSON-friendly events:
            {"event": "retrieve", "confidence": 0.42}
            {"event": "token", "text": "Firms must…"}
            {"event": "done", "citations": [...], "session_id": "…"}
        """
        t0 = perf_counter()
        session_uuid, history = await self._memory.load(
            tenant_id=tenant_id, session_id=session_id
        )
        t_mem = perf_counter()

        retrieval = await self._do_retrieval(tenant_id, question, filters, rerank)
        t_retr = perf_counter()
        log.info(
            "stream_ask: memory=%.0fms retrieve=%.0fms hits=%d conf=%.3f",
            (t_mem - t0) * 1000,
            (t_retr - t_mem) * 1000,
            len(retrieval.hits),
            retrieval.confidence,
        )

        yield {
            "event": "retrieve",
            "confidence": retrieval.confidence,
            "chunks": len(retrieval.hits),
        }

        collected: list[str] = []
        ctx = GatewayContext(
            tenant_id=tenant_id, user_id=user_id, purpose="chat", request_id=request_id
        )
        if not retrieval.hits:
            collected.append(REFUSAL_NO_CONTEXT)
            yield {"event": "token", "text": REFUSAL_NO_CONTEXT}
        else:
            messages = build_rag_messages(question, retrieval.hits, history=history)
            first_token_at: float | None = None
            async for token in self._gateway.stream(
                ctx,
                messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            ):
                if first_token_at is None:
                    first_token_at = perf_counter()
                    log.info(
                        "stream_ask: first_token_at=%.0fms (after retrieve)",
                        (first_token_at - t_retr) * 1000,
                    )
                collected.append(token)
                yield {"event": "token", "text": token}

        t_done = perf_counter()
        full_answer = "".join(collected)
        citations = extract_citations(full_answer, retrieval.hits)
        log.info(
            "stream_ask: total=%.0fms tokens=%d chars=%d",
            (t_done - t0) * 1000,
            len(collected),
            len(full_answer),
        )
        citation_payload = [c.model_dump(mode="json") for c in citations]
        await self._memory.append(
            tenant_id=tenant_id,
            session_id=session_uuid,
            user_id=user_id,
            question=question,
            answer=full_answer,
            citations=citation_payload,
        )
        yield {
            "event": "done",
            "session_id": str(session_uuid),
            "citations": citation_payload,
        }

    # ---- Internals -------------------------------------------------------

    async def _do_retrieval(
        self,
        tenant_id: UUID,
        question: str,
        filters: SearchFilters | None,
        rerank: bool = True,
    ) -> SearchOutcome:
        return await self._search.search(
            tenant_id=tenant_id,
            query=question,
            k=self._retrieve_k,
            filters=filters,
            rerank=rerank,
        )
