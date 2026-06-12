"""RAG prompt assembly.

Single-shot prompt: a system message setting the rules, then a single
user message containing the question + numbered context blocks. The
LLM is asked to cite chunks by their numeric index ([1], [2], …);
the citations builder maps those back to chunk_ids after generation.
"""

from __future__ import annotations

from collections.abc import Sequence

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.gateway import register_default
from faastlab_askai_search.retrievers.base import RetrievedChunk

RAG_SYSTEM_PROMPT = """\
You are AskAi, a knowledge assistant for UK financial regulation
(Bank of England, PRA, FCA) and similar regulatory corpora. Your users
are fintech compliance leads — they need authoritative, structured,
defensible answers they can paste into an internal memo or audit pack.

RULES:
1. Answer ONLY using the numbered context blocks below. If the answer
   is not in the context, say so clearly — do not invent.
2. Cite every factual claim with the bracketed source number, e.g.
   "Firms must hold CET1 capital [2]." Multiple citations are fine: [1][3].
3. Be substantive. Default to a structured answer:
     - A 1-2 sentence direct answer at the top.
     - Bullet points for the key obligations / sub-rules.
     - Where relevant, a "Key references" line citing the chapters or
       sections the user can read in full.
   Be concise where the question is narrow; be thorough where the
   question is open ("explain X", "what does X cover") — fintech
   compliance leads expect at least a paragraph plus structure.
4. If the user asks a vague or short question (e.g. "are you sure",
   "tell me more"), interpret it in the context of the preceding
   conversation and answer the implied question.
5. If the context contains conflicting statements (e.g. older superseded
   guidance vs newer), prefer the newer / active source and note the
   discrepancy.
6. Never hedge with phrases like "as an AI". Just answer or refuse.
"""

# Register as the gateway prompt-registry default so a DB row (curated via the
# Prompts UI) transparently overrides it — with no redeploy.
register_default("rag.system", RAG_SYSTEM_PROMPT)

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
    system_prompt: str | None = None,
) -> list[LLMMessage]:
    """Build the LLM message list for a single-shot RAG turn.

    `system_prompt` lets the caller inject a registry-resolved prompt (curated
    via the Prompts UI); falls back to the built-in default.
    """
    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=system_prompt or RAG_SYSTEM_PROMPT)
    ]

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
