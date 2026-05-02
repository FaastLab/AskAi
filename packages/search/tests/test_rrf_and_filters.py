"""Pure-logic tests: RRF fusion + filter clause assembly. No DB required."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.retrievers.base import RetrievedChunk
from faastlab_askai_search.retrievers.hybrid import RRF_CONSTANT, HybridRetriever
from faastlab_askai_search.retrievers.vector import _build_filter_clauses


def _hit(rank: int, score: float, chunk_id=None, doc_id=None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id or uuid4(),
        document_id=doc_id or uuid4(),
        tenant_id=uuid4(),
        document_title="t",
        content="c",
        score=score,
        rank=rank,
    )


def test_filter_clauses_only_active_default() -> None:
    tenant = uuid4()
    sql, params = _build_filter_clauses(tenant, SearchFilters())
    assert "c.tenant_id = :tenant_id" in sql
    assert "d.is_active = true" in sql
    assert params["tenant_id"] == tenant


def test_filter_clauses_doc_types_and_dates() -> None:
    tenant = uuid4()
    f = SearchFilters(
        doc_types=["policy", "rule"],
        effective_after=datetime(2024, 1, 1),
        effective_before=datetime(2025, 1, 1),
        only_active=False,
    )
    sql, params = _build_filter_clauses(tenant, f)
    assert "d.doc_type = ANY(:doc_types)" in sql
    assert "d.effective_date >= :effective_after" in sql
    assert "d.effective_date <= :effective_before" in sql
    assert "d.is_active = true" not in sql  # only_active False
    assert params["doc_types"] == ["policy", "rule"]


def test_filter_clauses_metadata_keys() -> None:
    tenant = uuid4()
    f = SearchFilters(metadata={"region": "UK", "format": "PDF"})
    sql, params = _build_filter_clauses(tenant, f)
    assert "d.metadata ->> :md_region_k = :md_region_v" in sql
    assert params["md_region_v"] == "UK"


@pytest.mark.asyncio
async def test_rrf_fusion_promotes_dual_hits() -> None:
    """A chunk that ranks well in BOTH retrievers should beat one that
    only appears in one — that's the whole point of RRF."""

    common = uuid4()
    only_vector = uuid4()
    only_keyword = uuid4()

    vector_hits = [
        _hit(rank=1, score=0.9, chunk_id=common),
        _hit(rank=2, score=0.7, chunk_id=only_vector),
    ]
    keyword_hits = [
        _hit(rank=1, score=0.8, chunk_id=only_keyword),
        _hit(rank=2, score=0.5, chunk_id=common),
    ]

    class _StubVector:
        async def retrieve(self, **kw): return vector_hits

    class _StubKeyword:
        async def retrieve(self, **kw): return keyword_hits

    hybrid = HybridRetriever(vector=_StubVector(), keyword=_StubKeyword())  # type: ignore[arg-type]
    fused = await hybrid.retrieve(tenant_id=uuid4(), query="x", k=3)

    assert fused[0].chunk_id == common  # in both lists → top
    chunk_ids = [h.chunk_id for h in fused]
    assert set(chunk_ids) == {common, only_vector, only_keyword}


def test_rrf_constant_is_60() -> None:
    # Documented invariant per Cormack et al. 2009.
    assert RRF_CONSTANT == 60
