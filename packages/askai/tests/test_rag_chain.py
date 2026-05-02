"""RAG chain tests with a fake LLM (no API calls)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from uuid import uuid4

import pytest

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_search.retrievers.base import RetrievedChunk

from faastlab_askai_askai.chains import RagChain


class FakeLLM:
    def __init__(self, response: str = "Answer with [1].") -> None:
        self.response = response
        self.last_messages: list[LLMMessage] | None = None

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        self.last_messages = list(messages)
        return self.response

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        self.last_messages = list(messages)
        for token in self.response.split(" "):
            yield token + " "


def _chunk(text: str = "context body") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        tenant_id=uuid4(),
        document_title="Doc",
        content=text,
        score=0.5,
    )


@pytest.mark.asyncio
async def test_rag_chain_calls_llm_with_context() -> None:
    llm = FakeLLM("Firms must hold capital [1].")
    chain = RagChain(llm)  # type: ignore[arg-type]
    result = await chain.answer("rule?", [_chunk("Capital required.")])
    assert result.text == "Firms must hold capital [1]."
    assert llm.last_messages is not None
    assert any("Capital required." in m.content for m in llm.last_messages)


@pytest.mark.asyncio
async def test_rag_chain_refuses_when_no_chunks() -> None:
    llm = FakeLLM()
    chain = RagChain(llm)  # type: ignore[arg-type]
    result = await chain.answer("rule?", [])
    assert "indexed" in result.text.lower() or "ingest" in result.text.lower()
    assert llm.last_messages is None  # no LLM call


@pytest.mark.asyncio
async def test_rag_chain_streams_tokens() -> None:
    llm = FakeLLM("hello world streaming")
    chain = RagChain(llm)  # type: ignore[arg-type]
    tokens: list[str] = []
    async for token in chain.stream_answer("q", [_chunk()]):
        tokens.append(token)
    assert "".join(tokens).strip() == "hello world streaming"
