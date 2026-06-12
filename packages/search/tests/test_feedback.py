"""Unit tests for the feedback-to-ranking nudge (#7) — pure, no DB."""

from __future__ import annotations

from uuid import UUID, uuid4

from faastlab_askai_search.feedback import (
    DocumentSignal,
    apply_feedback_nudge,
    normalize_query,
)
from faastlab_askai_search.retrievers.base import RetrievedChunk


def _hit(doc_id: UUID, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=doc_id,
        tenant_id=uuid4(),
        document_title=f"doc-{doc_id}",
        content="…",
        score=1.0 / rank,
        rank=rank,
    )


# ---- normalize_query -------------------------------------------------------


def test_normalize_lowercases_and_collapses_whitespace() -> None:
    assert normalize_query("  NR/L1   ADG ") == "nr/l1 adg"
    assert normalize_query("Hello\tWorld") == "hello world"


def test_normalize_same_question_matches() -> None:
    assert normalize_query("What is Consumer Duty?") == normalize_query(
        "what is consumer duty?"
    )


# ---- DocumentSignal.score --------------------------------------------------


def test_signal_zero_is_neutral() -> None:
    assert DocumentSignal(global_net=0, query_net=0).score() == 0.0


def test_signal_positive_and_bounded() -> None:
    s = DocumentSignal(global_net=100, query_net=100).score()
    assert 0.0 < s <= 1.0  # tanh is bounded by 1 (saturates for large input)


def test_signal_query_outweighs_global() -> None:
    # One upvote on this exact query beats one generic upvote.
    q = DocumentSignal(global_net=0, query_net=1).score()
    g = DocumentSignal(global_net=1, query_net=0).score()
    assert q > g > 0


def test_signal_negative_for_downvotes() -> None:
    assert DocumentSignal(global_net=-5, query_net=-2).score() < 0


# ---- apply_feedback_nudge --------------------------------------------------


def test_no_signals_leaves_order_unchanged() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    hits = [_hit(a, 1), _hit(b, 2), _hit(c, 3)]
    out = apply_feedback_nudge(hits, {})
    assert [h.document_id for h in out] == [a, b, c]
    assert [h.rank for h in out] == [1, 2, 3]


def test_upvoted_document_floats_up() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    hits = [_hit(a, 1), _hit(b, 2), _hit(c, 3)]
    # Strong query-specific signal on the 3rd-ranked doc lifts it (by up to
    # ~STRENGTH positions — bounded, so it lands near, not necessarily at, top).
    signals = {c: DocumentSignal(global_net=0, query_net=10)}
    out = apply_feedback_nudge(hits, signals)
    assert [h.document_id for h in out].index(c) < 2  # moved up from index 2


def test_downvoted_document_sinks() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    hits = [_hit(a, 1), _hit(b, 2), _hit(c, 3)]
    signals = {a: DocumentSignal(global_net=0, query_net=-10)}
    out = apply_feedback_nudge(hits, signals)
    assert [h.document_id for h in out].index(a) > 0  # sank from index 0


def test_nudge_is_bounded_cannot_leapfrog_everything() -> None:
    # A doc ranked far down (rank 6) with max signal moves up by at most
    # ~STRENGTH (2) positions — it cannot jump to the very top.
    ids = [uuid4() for _ in range(6)]
    hits = [_hit(d, i + 1) for i, d in enumerate(ids)]
    signals = {ids[5]: DocumentSignal(global_net=1000, query_net=1000)}
    out = apply_feedback_nudge(hits, signals)
    new_pos = [h.document_id for h in out].index(ids[5])
    assert new_pos >= 2  # moved up at most ~2 spots, not to position 0


def test_ranks_reassigned_contiguously() -> None:
    ids = [uuid4() for _ in range(4)]
    hits = [_hit(d, i + 1) for i, d in enumerate(ids)]
    signals = {ids[3]: DocumentSignal(global_net=0, query_net=5)}
    out = apply_feedback_nudge(hits, signals)
    assert [h.rank for h in out] == [1, 2, 3, 4]


def test_empty_hits_safe() -> None:
    assert apply_feedback_nudge([], {uuid4(): DocumentSignal(1, 1)}) == []
