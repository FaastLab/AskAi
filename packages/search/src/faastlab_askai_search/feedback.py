"""Feedback-to-ranking loop (knowledge layer #7).

Turns accumulated user reactions (thumbs up/down + corrections, stored in
`answer_feedback`) into a *bounded* nudge on retrieval ranking. The design
rule is that feedback may only **re-order** the candidates retrieval already
found — it can never inject a document, override grounding, or move a hit more
than a couple of positions. So a few stray clicks can't poison results, but a
consistent signal ("this manual page is the right answer for this question")
floats the right document up over time.

Two signals per document, combined and squashed into [-1, 1]:

* **global** — net votes for the document across *all* questions (a weak prior
  on document quality / usefulness).
* **query-specific** — net votes for the document on *this same question*
  (normalised). Much stronger: it's direct evidence for this query.

The squashed signal `s ∈ [-1, 1]` shifts a hit by `STRENGTH * s` rank
positions (up for positive, down for negative). `tanh` saturates, so the 50th
upvote counts for little more than the 5th — runaway boosting is impossible.

The store read and the nudge are split so the nudge is a pure, deterministic
function that unit-tests without a database.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_search.retrievers.base import RetrievedChunk

log = logging.getLogger(__name__)

# How far (in rank positions) a maximally-trusted document may move. Small on
# purpose: feedback tie-breaks and corrects, it does not rewrite the ranking.
NUDGE_STRENGTH = 2.0

# Relative weight of the two signals before the tanh squash. Query-specific
# evidence is worth ~3 generic upvotes.
_GLOBAL_WEIGHT = 0.15
_QUERY_WEIGHT = 0.45

# Bound how much history we read — feedback is human-paced and low-volume, so a
# recent window keeps the aggregation cheap and lets stale opinions age out.
_MAX_ROWS = 4000

_WS = re.compile(r"\s+")


def normalize_query(query: str) -> str:
    """Lowercase + collapse whitespace so 'NR/L1  ADG' and 'nr/l1 adg' match.

    Deliberately conservative — no stemming or stop-word removal — so the
    query-specific signal only fires on genuinely the same question.
    """
    return _WS.sub(" ", query.strip().lower())


@dataclass(frozen=True, slots=True)
class DocumentSignal:
    """Net feedback for one document: global votes + votes on this query."""

    global_net: int
    query_net: int

    def score(self) -> float:
        """Combined signal squashed to (-1, 1) via tanh."""
        import math

        raw = _GLOBAL_WEIGHT * self.global_net + _QUERY_WEIGHT * self.query_net
        return math.tanh(raw)


def apply_feedback_nudge(
    hits: list[RetrievedChunk],
    signals: dict[UUID, DocumentSignal],
    *,
    strength: float = NUDGE_STRENGTH,
) -> list[RetrievedChunk]:
    """Re-order `hits` by their current rank shifted by each document's signal.

    Pure and deterministic: `new_key = rank - strength * signal`. A document
    with no feedback (signal 0, or absent) keeps its rank, so the ordering is
    unchanged when there's no signal. Ties (e.g. two chunks of the same
    document) preserve the incoming order — `sorted` is stable. Returns a new
    list with `rank` reassigned 1..N; `score` is left untouched so confidence
    and downstream consumers see the real retrieval score.
    """
    if not signals or not hits:
        return hits

    def key(item: tuple[int, RetrievedChunk]) -> float:
        idx, hit = item
        sig = signals.get(hit.document_id)
        shift = strength * sig.score() if sig else 0.0
        # Use the incoming position (idx) as the base rank so the function is
        # robust even if callers didn't set `.rank`. Lower key sorts first.
        return idx - shift

    reordered = [hit for _, hit in sorted(enumerate(hits), key=key)]
    for new_rank, hit in enumerate(reordered, start=1):
        hit.rank = new_rank
    return reordered


class FeedbackStore:
    """Reads `answer_feedback` and aggregates it into per-document signals."""

    def __init__(self) -> None:
        # Imported lazily-ish at construction so the search package doesn't pay
        # the core.db import cost unless feedback is actually used.
        from faastlab_askai_core.db import get_sessionmaker

        self._sessionmaker = get_sessionmaker()

    async def signals_for(
        self,
        *,
        tenant_ids: UUID | list[UUID],
        query: str,
    ) -> dict[UUID, DocumentSignal]:
        """Aggregate feedback for the readable tenants into document signals.

        Returns an empty dict when there's no feedback (the common early case),
        which makes `apply_feedback_nudge` a no-op. Never raises — a failure to
        read feedback must not break search; it just means no nudge.
        """
        ids = [tenant_ids] if isinstance(tenant_ids, UUID) else list(tenant_ids)
        if not ids:
            return {}
        nquery = normalize_query(query)

        from faastlab_askai_core.db import AnswerFeedback

        try:
            async with self._sessionmaker() as session:
                rows = (
                    await session.execute(
                        select(
                            AnswerFeedback.rating,
                            AnswerFeedback.normalized_query,
                            AnswerFeedback.document_ids,
                        )
                        .where(AnswerFeedback.tenant_id.in_(ids))
                        .order_by(AnswerFeedback.id.desc())
                        .limit(_MAX_ROWS)
                    )
                ).all()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("feedback: signal read failed, skipping nudge: %s", exc)
            return {}

        global_net: dict[UUID, int] = {}
        query_net: dict[UUID, int] = {}
        for rating, row_nquery, document_ids in rows:
            for raw_id in document_ids or []:
                try:
                    doc_id = UUID(str(raw_id))
                except (ValueError, AttributeError, TypeError):
                    continue
                global_net[doc_id] = global_net.get(doc_id, 0) + int(rating)
                if row_nquery == nquery:
                    query_net[doc_id] = query_net.get(doc_id, 0) + int(rating)

        return {
            doc_id: DocumentSignal(
                global_net=global_net.get(doc_id, 0),
                query_net=query_net.get(doc_id, 0),
            )
            for doc_id in global_net.keys() | query_net.keys()
        }
