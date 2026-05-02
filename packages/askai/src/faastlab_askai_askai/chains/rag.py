"""Single-shot RAG chain — retrieve, prompt, LLM, cite.

Deliberately small: no LangChain abstraction here. We use the LLM
adapter directly so the codebase stays grokkable. LangGraph multi-step
flow comes in Phase 5.x for comparison / multi-hop questions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from faastlab_askai_core.adapters import LLMAdapter, LLMMessage
from faastlab_askai_search.retrievers.base import RetrievedChunk

from faastlab_askai_askai.prompts import REFUSAL_NO_CONTEXT, build_rag_messages


@dataclass(slots=True)
class RagAnswer:
    text: str
    chunks: list[RetrievedChunk]


class RagChain:
    """Wraps the LLM call + prompt assembly. Caller supplies retrieved chunks."""

    def __init__(
        self,
        llm: LLMAdapter,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = 700,
    ) -> None:
        self._llm = llm
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def answer(
        self,
        question: str,
        chunks: Sequence[RetrievedChunk],
        *,
        history: Sequence[LLMMessage] | None = None,
    ) -> RagAnswer:
        if not chunks:
            return RagAnswer(text=REFUSAL_NO_CONTEXT, chunks=[])

        messages = build_rag_messages(question, chunks, history=history)
        text = await self._llm.complete(
            messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return RagAnswer(text=text, chunks=list(chunks))

    async def stream_answer(
        self,
        question: str,
        chunks: Sequence[RetrievedChunk],
        *,
        history: Sequence[LLMMessage] | None = None,
    ) -> AsyncIterator[str]:
        if not chunks:
            yield REFUSAL_NO_CONTEXT
            return
        messages = build_rag_messages(question, chunks, history=history)
        async for token in self._llm.stream(
            messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        ):
            yield token
