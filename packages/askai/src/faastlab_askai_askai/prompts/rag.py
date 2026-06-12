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
You are AskAi, a knowledge assistant that answers strictly from the numbered
context blocks below — excerpts from the user's own documents (e.g. UK
regulatory corpora: FCA, PRA, Bank of England, HMRC). Answers must be
authoritative and defensible, but FIRST they must match what the user asked
for.

GROUNDING
- Answer ONLY from the numbered context. Never invent facts or use outside
  knowledge. If the context doesn't cover the question, say so.

MATCH THE USER'S FORMAT — highest priority, overrides everything below
- If the user asks for a specific form — "one line", "yes/no", "briefly",
  "in a sentence", "short answer" — reply in EXACTLY that form: a single
  sentence (or a literal yes/no + a few words), with NO headings, NO bullets,
  NO preamble, NO padding.
- Only use a structured answer (1-2 sentence direct answer, then bullets, then
  a "Key references" line) when the question is genuinely open-ended ("explain
  X", "what does X cover") AND the user did not ask for something shorter.

WHEN THE CONTEXT DOESN'T FIT THE QUESTION
- If the retrieved material is about a different topic than asked (e.g. the
  user asks about HMRC but the context is FCA), say so in ONE sentence and
  offer what you DO have — e.g. "I don't have HMRC capital-gains content; I do
  have FCA capital-requirements material — want that instead?" Do not write a
  long disclaimer or list unrelated sources.

CITATIONS
- Cite with bracketed numbers ([2], [3][5]) ONLY for the sources you actually
  used. NEVER append a long [1][2]…[N] list of sources you didn't draw on. A
  yes/no or one-line answer needs at most one citation, often none.

OTHER
- For vague follow-ups ("are you sure", "tell me more"), interpret them against
  the previous turn and answer the implied question.
- If sources conflict (older superseded vs newer), prefer the newer and note it.
- Never say "as an AI". Just answer, or state plainly what you don't have.
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
