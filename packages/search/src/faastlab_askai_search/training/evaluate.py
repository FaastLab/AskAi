"""Compare rerankers on a held-out query set.

Run search with reranker A vs reranker B vs no reranker, score with
standard IR metrics (MRR@10, NDCG@10, Recall@5, Recall@10), output a
side-by-side table you can paste into a thesis.

Held-out queries live in `training/eval_queries.jsonl` — one per line:
{
  "query": "What does FCA Consumer Duty say about cross-cutting rules?",
  "relevant_chunk_ids": ["uuid-1", "uuid-2", ...]
}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.db import Tenant, get_sessionmaker
from faastlab_askai_core.factory import reset_factory_cache
from faastlab_askai_search.filters import SearchFilters
from faastlab_askai_search.service import SearchService


@dataclass(slots=True)
class Metrics:
    label: str
    mrr_at_10: float
    ndcg_at_10: float
    recall_at_5: float
    recall_at_10: float
    avg_latency_ms: float


async def _resolve_tenant(slug_or_id: str) -> UUID:
    try:
        return UUID(slug_or_id)
    except ValueError:
        pass
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.execute(select(Tenant.id).where(Tenant.slug == slug_or_id))
    return row.scalar_one()


def _dcg(rels: list[float], k: int) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(rels[:k]))


def _ndcg_at_k(retrieved_ids: list[str], relevant: set[str], k: int) -> float:
    rels = [1.0 if cid in relevant else 0.0 for cid in retrieved_ids[:k]]
    ideal = sorted(rels, reverse=True)
    idcg = _dcg(ideal, k)
    return _dcg(rels, k) / idcg if idcg > 0 else 0.0


def _mrr_at_k(retrieved_ids: list[str], relevant: set[str], k: int) -> float:
    for rank, cid in enumerate(retrieved_ids[:k], start=1):
        if cid in relevant:
            return 1.0 / rank
    return 0.0


async def _evaluate_one(
    service: SearchService,
    tenant_id: UUID,
    queries: list[dict],
    label: str,
) -> Metrics:
    from time import perf_counter

    mrr = ndcg = r5 = r10 = 0.0
    total_latency = 0.0
    for q in queries:
        relevant = set(q["relevant_chunk_ids"])
        t0 = perf_counter()
        outcome = await service.search(
            tenant_id=tenant_id,
            query=q["query"],
            k=10,
            filters=SearchFilters(only_active=True),
        )
        total_latency += (perf_counter() - t0) * 1000
        retrieved_ids = [str(h.chunk_id) for h in outcome.hits]
        mrr += _mrr_at_k(retrieved_ids, relevant, k=10)
        ndcg += _ndcg_at_k(retrieved_ids, relevant, k=10)
        r5 += sum(1 for cid in retrieved_ids[:5] if cid in relevant) / max(
            len(relevant), 1
        )
        r10 += sum(1 for cid in retrieved_ids[:10] if cid in relevant) / max(
            len(relevant), 1
        )

    n = max(len(queries), 1)
    return Metrics(
        label=label,
        mrr_at_10=mrr / n,
        ndcg_at_10=ndcg / n,
        recall_at_5=r5 / n,
        recall_at_10=r10 / n,
        avg_latency_ms=total_latency / n,
    )


def _print_table(rows: list[Metrics]) -> None:
    print()
    print(
        f"{'Reranker':<35}  {'MRR@10':>8}  {'NDCG@10':>8}  {'R@5':>6}  {'R@10':>6}  {'ms':>6}"
    )
    print("-" * 80)
    for r in rows:
        print(
            f"{r.label:<35}  {r.mrr_at_10:>8.3f}  {r.ndcg_at_10:>8.3f}  "
            f"{r.recall_at_5:>6.3f}  {r.recall_at_10:>6.3f}  {r.avg_latency_ms:>6.0f}"
        )
    print()


def _load_eval(path: str | Path) -> list[dict]:
    out = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


async def main_async(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="askai-rerank-eval")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--queries", default="training/eval_queries.jsonl")
    parser.add_argument(
        "--rerankers",
        nargs="+",
        default=["none", "bge"],
        help="Which reranker_provider values to compare (also accepts model paths)",
    )
    args = parser.parse_args(argv)

    tenant_id = await _resolve_tenant(args.tenant)
    queries = _load_eval(args.queries)
    if not queries:
        raise SystemExit(f"No queries found in {args.queries}")

    rows: list[Metrics] = []
    for label in args.rerankers:
        # Override env, reset factory cache, run.
        import os

        if label == "none":
            os.environ["RERANKER_PROVIDER"] = "none"
        elif label == "bge":
            os.environ["RERANKER_PROVIDER"] = "bge"
        elif label == "cohere":
            os.environ["RERANKER_PROVIDER"] = "cohere"
        else:
            # Treat as a custom HF / local path for the bge adapter.
            os.environ["RERANKER_PROVIDER"] = "bge"
            os.environ["BGE_RERANKER_MODEL"] = label

        from faastlab_askai_core.config import get_settings

        get_settings.cache_clear()
        reset_factory_cache()
        service = SearchService()
        rows.append(await _evaluate_one(service, tenant_id, queries, label))

    _print_table(rows)
    return 0


def main() -> int:
    import sys

    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
