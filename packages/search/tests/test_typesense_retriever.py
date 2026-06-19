"""TypesenseRetriever: filter scoping, hit mapping, facet parsing, hybrid query.

No live Typesense — a fake client captures the search params (so we assert tenant
isolation + hybrid query are correct) and returns a canned result.
"""

from __future__ import annotations

from uuid import uuid4

from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.retrievers.typesense import (
    TypesenseRetriever,
    _build_filter_by,
    _parse_facets,
)


class _FakeEmbeddings:
    async def embed(self, text: str):
        return [0.1, 0.2, 0.3]


class _FakeDocs:
    def __init__(self, result, captured):
        self._result = result
        self._captured = captured

    def search(self, params):
        self._captured.update(params)
        return self._result


class _FakeCollection:
    def __init__(self, result, captured):
        self.documents = _FakeDocs(result, captured)


class _FakeCollections:
    def __init__(self, result, captured):
        self._coll = _FakeCollection(result, captured)

    def __getitem__(self, name):
        return self._coll


class _FakeClient:
    def __init__(self, result, captured):
        self.collections = _FakeCollections(result, captured)


def _retriever(result, captured):
    return TypesenseRetriever(
        client=_FakeClient(result, captured), embeddings=_FakeEmbeddings()
    )


# ---- pure helpers ----------------------------------------------------------


def test_filter_by_scopes_tenant_first_and_doctype() -> None:
    t1, t2 = uuid4(), uuid4()
    fb = _build_filter_by([t1, t2], SearchFilters(only_active=True, doc_types=["guidance"]))
    assert fb.startswith(f"tenant_id:=[`{t1}`, `{t2}`]")
    assert "is_active:=true" in fb
    assert "doc_type:=[`guidance`]" in fb


def test_parse_facets() -> None:
    raw = [{"field_name": "doc_type", "counts": [
        {"value": "guidance", "count": 12}, {"value": "policy", "count": 3}]}]
    assert _parse_facets(raw) == {"doc_type": {"guidance": 12, "policy": 3}}


# ---- retrieve --------------------------------------------------------------


async def test_retrieve_builds_hybrid_query_and_maps_hits() -> None:
    cid, did, tid = uuid4(), uuid4(), uuid4()
    result = {
        "hits": [
            {
                "vector_distance": 0.1,
                "document": {
                    "chunk_id": str(cid),
                    "document_id": str(did),
                    "tenant_id": str(tid),
                    "document_title": "FCA Handbook",
                    "content": "Firms must report suspicions.",
                    "doc_type": "guidance",
                    "is_active": True,
                    "page_number": 4,
                },
            }
        ],
        "facet_counts": [
            {"field_name": "doc_type", "counts": [{"value": "guidance", "count": 1}]}
        ],
    }
    captured: dict = {}
    hits, facets = await _retriever(result, captured).retrieve_with_facets(
        tenant_id=tid, query="reporting suspicions", k=5
    )

    # Hybrid: both keyword query_by AND a vector_query were sent.
    assert captured["query_by"] == "content,document_title"
    assert captured["vector_query"].startswith("embedding:([")
    # Tenant isolation present in the filter.
    assert f"tenant_id:=[`{tid}`]" in captured["filter_by"]
    # Vectors never returned over the wire.
    assert captured["exclude_fields"] == "embedding"
    # Mapped hit.
    assert hits[0].chunk_id == cid
    assert hits[0].document_title == "FCA Handbook"
    assert abs(hits[0].score - 0.9) < 1e-9  # 1 - 0.1
    assert facets == {"doc_type": {"guidance": 1}}


async def test_instant_counts_is_keyword_only_and_returns_found() -> None:
    tid = uuid4()
    result = {
        "found": 423,
        "facet_counts": [
            {"field_name": "doc_type", "counts": [
                {"value": "guidance", "count": 210}, {"value": "policy", "count": 88}]}
        ],
    }
    captured: dict = {}
    found, facets = await _retriever(result, captured).instant_counts(
        tenant_id=tid, query="capital"
    )
    assert found == 423
    assert facets == {"doc_type": {"guidance": 210, "policy": 88}}
    # Keyword-only + counts-only: no vector_query, no documents fetched.
    assert "vector_query" not in captured
    assert captured["per_page"] == 0
    assert captured["facet_by"] == "doc_type"
    assert f"tenant_id:=[`{tid}`]" in captured["filter_by"]


async def test_retrieve_passes_tenant_union_for_public_corpus() -> None:
    own, public = uuid4(), uuid4()
    captured: dict = {}
    await _retriever({"hits": []}, captured).retrieve(
        tenant_id=[own, public], query="x", k=3
    )
    assert f"tenant_id:=[`{own}`, `{public}`]" in captured["filter_by"]
