"""Pure-logic tests: keyphrase JSON parsing + map-reduce slicing."""

from __future__ import annotations

import tiktoken

from faastlab_askai_summarisation.keyphrases import _parse_phrases
from faastlab_askai_summarisation.map_reduce import (
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_SLICE_TOKENS,
    MapReduceSummariser,
)


def test_parse_phrases_strips_code_fence() -> None:
    raw = '```json\n["CET1 capital ratio", "Tier 2 instruments"]\n```'
    assert _parse_phrases(raw, max_phrases=12) == [
        "CET1 capital ratio",
        "Tier 2 instruments",
    ]


def test_parse_phrases_handles_extra_commentary() -> None:
    raw = (
        "Here are the keyphrases:\n"
        '["LCR", "consumer duty", "operational resilience"]'
    )
    out = _parse_phrases(raw, max_phrases=12)
    assert out == ["LCR", "consumer duty", "operational resilience"]


def test_parse_phrases_dedupes_and_caps() -> None:
    raw = '["A", "A", "B", "C", "D"]'
    out = _parse_phrases(raw, max_phrases=3)
    assert out == ["A", "B", "C"]


def test_parse_phrases_invalid_returns_empty() -> None:
    assert _parse_phrases("not even json", max_phrases=12) == []
    assert _parse_phrases('{"k": 1}', max_phrases=12) == []


def test_slice_short_text_one_slice() -> None:
    summariser = _summariser_for_test()
    text = "Short text under the slice budget."
    slices = summariser._slice(text)  # noqa: SLF001
    assert len(slices) == 1


def test_slice_long_text_many_slices_with_overlap() -> None:
    summariser = _summariser_for_test()
    enc = tiktoken.get_encoding("cl100k_base")
    # Build a string > 1 slice in token terms.
    target_tokens = DEFAULT_SLICE_TOKENS * 3
    text = " ".join(["regulatory"] * target_tokens)
    slices = summariser._slice(text)  # noqa: SLF001
    assert len(slices) >= 3

    # Each slice should fit within the budget.
    for s in slices:
        assert len(enc.encode(s)) <= DEFAULT_SLICE_TOKENS + DEFAULT_OVERLAP_TOKENS


def _summariser_for_test() -> MapReduceSummariser:
    """Build a MapReduceSummariser without instantiating the real LLM."""

    class _NullLLM:
        async def complete(self, *_args, **_kw) -> str:
            return ""

        async def stream(self, *_args, **_kw):  # pragma: no cover
            if False:
                yield ""

    return MapReduceSummariser(llm=_NullLLM())  # type: ignore[arg-type]
