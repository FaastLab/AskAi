"""Unit tests for the sovereign TEI reranker (GPU-served, over HTTP).

httpx is stubbed so no network/GPU is needed — the test verifies request
shaping, re-ordering from the TEI response, top_n, and error handling.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from faastlab_askai_core.config import Settings
from faastlab_askai_core.exceptions import RerankerError
from faastlab_askai_search.rerankers import tei as tei_mod
from faastlab_askai_search.rerankers.tei import TeiReranker
from faastlab_askai_search.retrievers.base import RetrievedChunk


def _chunk(content: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        tenant_id=uuid4(),
        document_title="doc",
        content=content,
        score=0.0,
        rank=rank,
    )


def _settings(url: str | None = "http://gpu:8081", *, max_batch: int = 32) -> Settings:
    return Settings(
        reranker_base_url=url,
        reranker_provider="tei",
        reranker_max_batch_size=max_batch,
    )


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.captured: dict | None = None

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Async-context-manager stand-in for httpx.AsyncClient."""

    def __init__(self, payload, capture: dict):
        self._payload = payload
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json):
        self._capture["url"] = url
        self._capture["json"] = json
        return _FakeResponse(self._payload)


def _patch_httpx(monkeypatch, payload, capture):
    monkeypatch.setattr(
        tei_mod.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload, capture)
    )


def test_missing_base_url_raises() -> None:
    with pytest.raises(RerankerError):
        TeiReranker(_settings(url=None))


async def test_empty_hits_short_circuits() -> None:
    rr = TeiReranker(_settings())
    assert await rr.rerank("q", []) == []


async def test_reorders_by_tei_scores(monkeypatch) -> None:
    capture: dict = {}
    # TEI says hit index 2 is best, then 0, then 1.
    _patch_httpx(
        monkeypatch,
        [{"index": 2, "score": 0.9}, {"index": 0, "score": 0.5}, {"index": 1, "score": 0.1}],
        capture,
    )
    hits = [_chunk("a", 1), _chunk("b", 2), _chunk("c", 3)]
    out = await TeiReranker(_settings()).rerank("why?", hits)

    assert [c.content for c in out] == ["c", "a", "b"]
    assert [c.rank for c in out] == [1, 2, 3]
    assert out[0].score == pytest.approx(0.9)
    # request was shaped correctly
    assert capture["url"] == "http://gpu:8081/rerank"
    assert capture["json"] == {"query": "why?", "texts": ["a", "b", "c"]}


async def test_top_n_truncates(monkeypatch) -> None:
    capture: dict = {}
    _patch_httpx(
        monkeypatch,
        [{"index": 0, "score": 0.9}, {"index": 1, "score": 0.8}, {"index": 2, "score": 0.7}],
        capture,
    )
    hits = [_chunk("a", 1), _chunk("b", 2), _chunk("c", 3)]
    out = await TeiReranker(_settings()).rerank("q", hits, top_n=2)
    assert len(out) == 2
    assert [c.content for c in out] == ["a", "b"]


async def test_unsorted_response_is_sorted(monkeypatch) -> None:
    capture: dict = {}
    # Deliberately out of order — adapter must sort defensively.
    _patch_httpx(
        monkeypatch,
        [{"index": 0, "score": 0.2}, {"index": 1, "score": 0.95}],
        capture,
    )
    hits = [_chunk("low", 1), _chunk("high", 2)]
    out = await TeiReranker(_settings()).rerank("q", hits)
    assert [c.content for c in out] == ["high", "low"]


async def test_http_failure_raises_reranker_error(monkeypatch) -> None:
    def _boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tei_mod.httpx, "AsyncClient", _boom)
    with pytest.raises(RerankerError):
        await TeiReranker(_settings()).rerank("q", [_chunk("a", 1)])


class _ScoringClient:
    """Fake client that scores each batch by a content->score map, so we can
    assert batches are merged + globally re-sorted (not just per-batch)."""

    def __init__(self, scores: dict[str, float], calls: list[int]):
        self._scores = scores
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json):
        texts = json["texts"]
        self._calls.append(len(texts))
        # TEI would never return >32; assert the adapter respects the cap.
        assert len(texts) <= 32
        payload = [
            {"index": i, "score": self._scores[t]} for i, t in enumerate(texts)
        ]
        return _FakeResponse(payload)


async def test_batches_large_pool_and_merges(monkeypatch) -> None:
    scores = {"a": 0.5, "b": 0.9, "c": 0.1, "d": 0.95, "e": 0.3}
    calls: list[int] = []
    monkeypatch.setattr(
        tei_mod.httpx, "AsyncClient", lambda *a, **k: _ScoringClient(scores, calls)
    )
    hits = [_chunk(c, i + 1) for i, c in enumerate(scores)]
    # max_batch=2 over 5 hits -> 3 requests (2, 2, 1)
    out = await TeiReranker(_settings(max_batch=2)).rerank("q", hits)

    assert calls == [2, 2, 1]                       # split into batches
    assert [c.content for c in out] == ["d", "b", "a", "e", "c"]   # global sort
    assert [c.rank for c in out] == [1, 2, 3, 4, 5]


async def test_top_n_applies_after_merge(monkeypatch) -> None:
    scores = {"a": 0.5, "b": 0.9, "c": 0.1, "d": 0.95}
    calls: list[int] = []
    monkeypatch.setattr(
        tei_mod.httpx, "AsyncClient", lambda *a, **k: _ScoringClient(scores, calls)
    )
    hits = [_chunk(c, i + 1) for i, c in enumerate(scores)]
    out = await TeiReranker(_settings(max_batch=2)).rerank("q", hits, top_n=2)
    assert [c.content for c in out] == ["d", "b"]    # best 2 across all batches
