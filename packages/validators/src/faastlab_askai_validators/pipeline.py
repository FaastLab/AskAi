"""ValidatorPipeline — regulatory report → traffic-light verdict.

Flow per claim:
1. Extract distinct claims from the report (LLM, JSON output).
2. For each claim, retrieve the top-k most relevant chunks from the
   tenant's authoritative corpus.
3. Adjudicate the claim against the retrieved context (LLM, JSON output).
4. Aggregate per-claim verdicts into a single traffic-light status:
     green  = no contradictions, ≥X% supported
     amber  = mostly unsupported, no contradictions
     red    = ≥1 contradiction

Each claim verdict carries citations back to the supporting chunks so
the reviewer can drill in.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from faastlab_askai_core.adapters import LLMAdapter, LLMMessage
from faastlab_askai_core.factory import get_llm
from faastlab_askai_core.schemas.search import Citation
from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.retrievers.base import RetrievedChunk
from faastlab_askai_search.service import SearchService

from faastlab_askai_validators.prompts import (
    ADJUDICATE_PROMPT,
    CLAIM_EXTRACTION_PROMPT,
)

log = logging.getLogger(__name__)

VerdictType = Literal["supported", "contradicted", "unsupported"]
TrafficLight = Literal["green", "amber", "red"]


@dataclass(slots=True)
class ClaimVerdict:
    claim: str
    verdict: VerdictType
    rationale: str
    citations: list[Citation] = field(default_factory=list)


@dataclass(slots=True)
class ValidatorResult:
    overall: TrafficLight
    summary: str
    claims: list[ClaimVerdict]
    total_claims: int
    supported: int
    contradicted: int
    unsupported: int
    generated_at: datetime


class ValidatorPipeline:
    def __init__(
        self,
        *,
        llm: LLMAdapter | None = None,
        search: SearchService | None = None,
        retrieve_k: int = 6,
        green_threshold: float = 0.7,
    ) -> None:
        self._llm = llm or get_llm()
        self._search = search or SearchService()
        self._retrieve_k = retrieve_k
        self._green_threshold = green_threshold

    async def validate_report(
        self,
        *,
        tenant_id: UUID,
        report_text: str,
        filters: SearchFilters | None = None,
    ) -> ValidatorResult:
        if not report_text.strip():
            raise ValueError("report_text is empty")

        claims = await self._extract_claims(report_text)
        log.info("Extracted %d claims", len(claims))

        verdicts: list[ClaimVerdict] = []
        for claim in claims:
            verdict = await self._adjudicate_claim(
                claim=claim, tenant_id=tenant_id, filters=filters
            )
            verdicts.append(verdict)

        supported = sum(1 for v in verdicts if v.verdict == "supported")
        contradicted = sum(1 for v in verdicts if v.verdict == "contradicted")
        unsupported = sum(1 for v in verdicts if v.verdict == "unsupported")

        overall = _traffic_light(
            supported=supported,
            contradicted=contradicted,
            total=max(len(verdicts), 1),
            green_threshold=self._green_threshold,
        )
        summary = self._summarise(overall, supported, contradicted, unsupported)

        return ValidatorResult(
            overall=overall,
            summary=summary,
            claims=verdicts,
            total_claims=len(verdicts),
            supported=supported,
            contradicted=contradicted,
            unsupported=unsupported,
            generated_at=datetime.now(UTC),
        )

    # ---- Internals -------------------------------------------------------

    async def _extract_claims(self, report_text: str) -> list[str]:
        prompt = CLAIM_EXTRACTION_PROMPT.format(report=report_text[:20000])
        raw = await self._llm.complete(
            [LLMMessage(role="user", content=prompt)],
            temperature=0.0,
            max_tokens=1500,
        )
        return _parse_json_array_of_strings(raw, max_items=25)

    async def _adjudicate_claim(
        self,
        *,
        claim: str,
        tenant_id: UUID,
        filters: SearchFilters | None,
    ) -> ClaimVerdict:
        retrieval = await self._search.search(
            tenant_id=tenant_id,
            query=claim,
            k=self._retrieve_k,
            filters=filters or SearchFilters(),
        )
        if not retrieval.hits:
            return ClaimVerdict(
                claim=claim,
                verdict="unsupported",
                rationale="No relevant authoritative material found.",
            )

        context = _format_context(retrieval.hits)
        prompt = ADJUDICATE_PROMPT.format(claim=claim, context=context)
        raw = await self._llm.complete(
            [LLMMessage(role="user", content=prompt)],
            temperature=0.0,
            max_tokens=400,
        )
        verdict, rationale, evidence_idx = _parse_adjudication(raw)
        evidence_chunks = [
            retrieval.hits[i - 1]
            for i in evidence_idx
            if 1 <= i <= len(retrieval.hits)
        ]
        return ClaimVerdict(
            claim=claim,
            verdict=verdict,
            rationale=rationale,
            citations=[_chunk_to_citation(c) for c in evidence_chunks],
        )

    @staticmethod
    def _summarise(
        overall: TrafficLight,
        supported: int,
        contradicted: int,
        unsupported: int,
    ) -> str:
        return (
            f"{overall.upper()}: "
            f"{supported} supported, {contradicted} contradicted, "
            f"{unsupported} unsupported."
        )


# ---- Parsing helpers -------------------------------------------------------


def _parse_json_array_of_strings(raw: str, *, max_items: int) -> list[str]:
    text = raw.strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].lstrip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    items: list[str] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
        if len(items) >= max_items:
            break
    return items


def _parse_adjudication(raw: str) -> tuple[VerdictType, str, list[int]]:
    text = raw.strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].lstrip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ("unsupported", "Could not parse adjudication response.", [])
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return ("unsupported", "Invalid JSON in adjudication response.", [])
    verdict_raw = str(obj.get("verdict", "unsupported")).lower()
    verdict: VerdictType = (
        verdict_raw if verdict_raw in {"supported", "contradicted", "unsupported"} else "unsupported"  # type: ignore[assignment]
    )
    rationale = str(obj.get("rationale") or "")
    evidence = obj.get("evidence") or []
    evidence_idx: list[int] = [int(i) for i in evidence if isinstance(i, int) or (
        isinstance(i, str) and i.isdigit()
    )]
    return verdict, rationale, evidence_idx


def _format_context(chunks: Sequence[RetrievedChunk]) -> str:
    parts = []
    for i, c in enumerate(chunks, start=1):
        loc = c.document_title
        if c.page_number is not None:
            loc += f" · page {c.page_number}"
        parts.append(f"[{i}] {loc}\n{c.content[:600].strip()}")
    return "\n\n".join(parts)


def _chunk_to_citation(chunk: RetrievedChunk) -> Citation:
    snippet = chunk.content[:240].strip().replace("\n", " ")
    return Citation(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        document_title=chunk.document_title,
        page_number=chunk.page_number,
        section_path=chunk.section_path,
        snippet=snippet,
    )


def _traffic_light(
    *,
    supported: int,
    contradicted: int,
    total: int,
    green_threshold: float,
) -> TrafficLight:
    if contradicted > 0:
        return "red"
    if supported / total >= green_threshold:
        return "green"
    return "amber"
