"""Map-reduce summarisation pipeline.

For long documents we slice the full text into LLM-sized windows, ask
the model to summarise each, then ask once more to fuse the slice
summaries into a coherent whole-document summary.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import tiktoken

from faastlab_askai_core.adapters import LLMAdapter, LLMMessage
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.factory import get_llm

from faastlab_askai_summarisation.prompts import (
    FOCUSED_PROMPT,
    MAP_PROMPT,
    REDUCE_PROMPT,
)

DEFAULT_SLICE_TOKENS = 2500
DEFAULT_OVERLAP_TOKENS = 100
MAP_PARALLELISM = 5


@dataclass(slots=True)
class SummariseResult:
    summary: str
    slice_summaries: list[str]
    slices_used: int


class MapReduceSummariser:
    def __init__(
        self,
        *,
        llm: LLMAdapter | None = None,
        settings: Settings | None = None,
        slice_tokens: int = DEFAULT_SLICE_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        parallelism: int = MAP_PARALLELISM,
        encoding_name: str = "cl100k_base",
    ) -> None:
        self._llm = llm or get_llm()
        self._settings = settings or get_settings()
        self._slice_tokens = slice_tokens
        self._overlap_tokens = overlap_tokens
        self._parallelism = parallelism
        self._encoding = tiktoken.get_encoding(encoding_name)

    async def summarise(self, text: str) -> SummariseResult:
        if not text.strip():
            return SummariseResult(summary="", slice_summaries=[], slices_used=0)

        slices = self._slice(text)
        if len(slices) == 1:
            # Short doc — skip the reduce step.
            summary = await self._call(MAP_PROMPT.format(slice=slices[0]))
            return SummariseResult(
                summary=summary, slice_summaries=[summary], slices_used=1
            )

        slice_summaries = await self._map(slices)
        joined = "\n\n".join(
            f"- ({i + 1}) {s.strip()}" for i, s in enumerate(slice_summaries)
        )
        whole = await self._call(REDUCE_PROMPT.format(summaries=joined))
        return SummariseResult(
            summary=whole,
            slice_summaries=slice_summaries,
            slices_used=len(slices),
        )

    async def focused_summarise(self, summary_text: str, query: str) -> str:
        """Bias the existing whole-document summary toward `query`."""
        if not summary_text.strip():
            return ""
        return await self._call(
            FOCUSED_PROMPT.format(summary=summary_text, query=query)
        )

    # ---- Internals -------------------------------------------------------

    def _slice(self, text: str) -> list[str]:
        """Token-aware slicing (best-effort on word boundaries)."""
        tokens = self._encoding.encode(text)
        if len(tokens) <= self._slice_tokens:
            return [text]
        slices: list[str] = []
        step = self._slice_tokens - self._overlap_tokens
        for start in range(0, len(tokens), step):
            window = tokens[start : start + self._slice_tokens]
            slices.append(self._encoding.decode(window))
            if start + self._slice_tokens >= len(tokens):
                break
        return slices

    async def _map(self, slices: list[str]) -> list[str]:
        sem = asyncio.Semaphore(self._parallelism)

        async def _one(s: str) -> str:
            async with sem:
                return await self._call(MAP_PROMPT.format(slice=s))

        return await asyncio.gather(*(_one(s) for s in slices))

    async def _call(self, prompt: str) -> str:
        return await self._llm.complete(
            [LLMMessage(role="user", content=prompt)],
            temperature=0.0,
            max_tokens=600,
        )
