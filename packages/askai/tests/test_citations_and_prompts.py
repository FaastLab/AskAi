"""Pure-logic tests: prompt assembly + citation extraction. No LLM/DB."""

from __future__ import annotations

from uuid import uuid4

from faastlab_askai_search.retrievers.base import RetrievedChunk

from faastlab_askai_askai.citations import extract_citations
from faastlab_askai_askai.prompts import (
    REFUSAL_NO_CONTEXT,
    RAG_SYSTEM_PROMPT,
    build_rag_messages,
)


def _chunk(text: str, *, title: str = "BoE SS1/19", page: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        tenant_id=uuid4(),
        document_title=title,
        content=text,
        score=0.5,
        rank=1,
        page_number=page,
    )


def test_build_rag_messages_includes_system_and_numbered_context() -> None:
    chunks = [_chunk("Firms must hold capital."), _chunk("Tier 1 minimum is 4.5%.")]
    msgs = build_rag_messages("What's the capital rule?", chunks)
    assert msgs[0].role == "system"
    assert "ONLY using the numbered context" in msgs[0].content
    assert RAG_SYSTEM_PROMPT in msgs[0].content
    assert msgs[-1].role == "user"
    user_text = msgs[-1].content
    assert "[1]" in user_text and "[2]" in user_text
    assert "Firms must hold capital." in user_text


def test_build_rag_messages_handles_history() -> None:
    from faastlab_askai_core.adapters import LLMMessage

    history = [
        LLMMessage(role="user", content="Earlier question"),
        LLMMessage(role="assistant", content="Earlier answer [1]"),
    ]
    msgs = build_rag_messages("Follow up?", [_chunk("…")], history=history)
    assert msgs[1].content == "Earlier question"
    assert msgs[2].content == "Earlier answer [1]"
    assert msgs[3].role == "user"
    assert "Follow up?" in msgs[3].content


def test_build_rag_messages_no_chunks() -> None:
    msgs = build_rag_messages("Q?", [])
    assert "(none — no documents matched this query)" in msgs[-1].content


def test_extract_citations_dedups_in_order() -> None:
    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]
    answer = "First [1][2]. Then [2] again. Finally [3] and [1] once more."
    cites = extract_citations(answer, chunks)
    titles = [c.snippet for c in cites]
    # 3 unique citations, in first-mention order: 1, 2, 3
    assert len(cites) == 3
    assert titles[0] == "a"
    assert titles[1] == "b"
    assert titles[2] == "c"


def test_extract_citations_ignores_out_of_range() -> None:
    chunks = [_chunk("only one")]
    answer = "Out of range [9] but in range [1]."
    cites = extract_citations(answer, chunks)
    assert len(cites) == 1
    assert cites[0].snippet == "only one"


def test_extract_citations_truncates_long_snippets() -> None:
    long_text = "word " * 100  # 500 chars
    cites = extract_citations("[1]", [_chunk(long_text)], snippet_chars=80)
    assert len(cites[0].snippet) <= 90
    assert cites[0].snippet.endswith("…")


def test_refusal_constant_is_meaningful() -> None:
    assert "ingest" in REFUSAL_NO_CONTEXT.lower() or "indexed" in REFUSAL_NO_CONTEXT.lower()
