"""Generate (query, positive, negative) triplets from an ingested corpus.

Strategy:
1. Sample N chunks from the tenant's `chunks` table.
2. For each, ask the configured LLM to write 1-3 plausible questions
   the chunk would answer (synthetic queries).
3. The chunk itself is the *positive*. The *hard negative* is sampled
   from the SAME document but a different chunk (high topic overlap,
   wrong specifics — best signal for the reranker).
4. Optionally a *random negative* from a different document.

Output: JSONL where each line is one Triplet.

Then run `python -m faastlab_askai_search.training.train` to fine-tune
bge-reranker-base on the triplets.
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.db import Chunk, get_sessionmaker
from faastlab_askai_core.factory import get_llm

QUESTION_PROMPT = """\
Read the regulatory passage below and write 1-3 short, distinct
questions a regulated firm might ask whose answer is in this passage.

Output: a JSON array of strings, max 3 items, no commentary.

PASSAGE:
{passage}
"""


@dataclass(slots=True)
class Triplet:
    query: str
    positive: str
    negative: str
    document_id: str
    positive_chunk_id: str
    negative_chunk_id: str
    negative_kind: str  # "same_doc" | "random"


async def generate_triplets(
    *,
    tenant_id: UUID,
    sample_size: int = 200,
    same_doc_negatives_per_query: int = 1,
    random_negatives_per_query: int = 0,
    output_path: Path | str = "training/triplets.jsonl",
    seed: int = 42,
) -> int:
    """Generate triplets and write JSONL. Returns the number written.

    `sample_size` is the number of POSITIVE chunks to sample. Each one
    yields 1-3 queries, each query produces 1+ triplets.
    """
    rng = random.Random(seed)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    sm = get_sessionmaker()
    llm = get_llm()

    async with sm() as session:
        rows = await session.execute(
            select(
                Chunk.id, Chunk.document_id, Chunk.content
            ).where(Chunk.tenant_id == tenant_id)
        )
        all_chunks = rows.all()

    if not all_chunks:
        raise RuntimeError(
            "No chunks for this tenant — run `make demo-corpus` first."
        )

    sample = rng.sample(all_chunks, min(sample_size, len(all_chunks)))
    by_doc: dict[UUID, list] = {}
    for c in all_chunks:
        by_doc.setdefault(c.document_id, []).append(c)

    written = 0
    with out.open("w", encoding="utf-8") as fh:
        for chunk in sample:
            queries = await _make_queries(llm, chunk.content)
            for query in queries:
                # same-doc negatives (high signal — same topic, wrong specifics)
                same_doc_pool = [
                    c for c in by_doc[chunk.document_id] if c.id != chunk.id
                ]
                for neg in rng.sample(
                    same_doc_pool,
                    min(same_doc_negatives_per_query, len(same_doc_pool)),
                ):
                    fh.write(
                        _emit(
                            query, chunk, neg, kind="same_doc"
                        )
                    )
                    written += 1
                # random negatives (low signal but cheap)
                if random_negatives_per_query > 0:
                    pool = [c for c in all_chunks if c.document_id != chunk.document_id]
                    for neg in rng.sample(
                        pool, min(random_negatives_per_query, len(pool))
                    ):
                        fh.write(
                            _emit(query, chunk, neg, kind="random")
                        )
                        written += 1

    return written


async def _make_queries(llm, passage: str) -> list[str]:
    raw = await llm.complete(
        [LLMMessage(role="user", content=QUESTION_PROMPT.format(passage=passage[:2000]))],
        temperature=0.7,
        max_tokens=300,
    )
    text = raw.strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].lstrip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [q.strip() for q in data if isinstance(q, str) and q.strip()][:3]


def _emit(query: str, pos, neg, *, kind: str) -> str:
    triplet = Triplet(
        query=query,
        positive=pos.content,
        negative=neg.content,
        document_id=str(pos.document_id),
        positive_chunk_id=str(pos.id),
        negative_chunk_id=str(neg.id),
        negative_kind=kind,
    )
    return json.dumps(asdict(triplet)) + "\n"


# ---- CLI -------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="askai-rerank-triplets")
    parser.add_argument("--tenant", required=True, help="Tenant slug or UUID")
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--same-doc-negs", type=int, default=1)
    parser.add_argument("--random-negs", type=int, default=0)
    parser.add_argument("--output", default="training/triplets.jsonl")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    async def _run() -> None:
        from faastlab_askai_core.db import Tenant

        sm = get_sessionmaker()
        try:
            tid = UUID(args.tenant)
        except ValueError:
            async with sm() as s:
                row = await s.execute(
                    select(Tenant.id).where(Tenant.slug == args.tenant)
                )
                tid = row.scalar_one()

        n = await generate_triplets(
            tenant_id=tid,
            sample_size=args.sample_size,
            same_doc_negatives_per_query=args.same_doc_negs,
            random_negatives_per_query=args.random_negs,
            output_path=args.output,
            seed=args.seed,
        )
        print(f"Wrote {n} triplets to {args.output}")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
