"""RAG prompt assembly.

Single-shot prompt: a system message setting the rules, then a single
user message containing the question + numbered context blocks. The
LLM is asked to cite chunks by their numeric index ([1], [2], …);
the citations builder maps those back to chunk_ids after generation.
"""

from __future__ import annotations

from collections.abc import Sequence

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_search.retrievers.base import RetrievedChunk

RAG_SYSTEM_PROMPT = """\
You are AskAi, a knowledge assistant for UK financial regulation
(Bank of England, PRA, FCA) and similar regulatory corpora.

RULES:
1. Answer ONLY using the numbered context blocks below. If the answer
   is not in the context, say so clearly — do not invent.
2. Cite every factual claim with the bracketed source number, e.g.
   "Firms must hold CET1 capital [2]." Multiple citations are fine: [1][3].
3. Be concise. Plain English first; quote regulator language only when
   necessary for accuracy.
4. If the context contains conflicting statements (e.g. older superseded
   guidance vs newer), prefer the newer / active source and note the
   discrepancy.
5. Never hedge with phrases like "as an AI". Just answer or refuse.
"""

REFUSAL_NO_CONTEXT = (
    "I don't have any indexed material that answers this. Try a different "
    "phrasing, or ingest the relevant document into AskAi first."
)


def _format_context(chunks: Sequence[RetrievedChunk]) -> str:
    """Number context blocks 1..N with title + page + section so the model
    can cite them and we can map numbers back to chunk_ids."""
    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        location_bits: list[str] = [chunk.document_title]
        if chunk.page_number is not None:
            location_bits.append(f"page {chunk.page_number}")
        if chunk.section_path:
            location_bits.append(chunk.section_path)
        location = " · ".join(location_bits)

        snippet = chunk.content.strip().replace("\n", " ")
        parts.append(f"[{i}] {location}\n{snippet}")
    return "\n\n".join(parts)


def build_rag_messages(
    question: str,
    chunks: Sequence[RetrievedChunk],
    *,
    history: Sequence[LLMMessage] | None = None,
) -> list[LLMMessage]:
    """Build the LLM message list for a single-shot RAG turn."""
    messages: list[LLMMessage] = [LLMMessage(role="system", content=RAG_SYSTEM_PROMPT)]

    if history:
        messages.extend(history)

    if not chunks:
        # No retrieval results — short-circuit with a polite refusal so we
        # don't hallucinate. The service layer can also catch this earlier.
        messages.append(
            LLMMessage(
                role="user",
                content=(
                    f"Question: {question}\n\n"
                    "Context: (none — no documents matched this query)"
                ),
            )
        )
        return messages

    user_content = (
        f"Question: {question}\n\n"
        f"Context:\n{_format_context(chunks)}\n\n"
        "Answer using only the context above. Cite sources by number."
    )
    messages.append(LLMMessage(role="user", content=user_content))
    return messages
