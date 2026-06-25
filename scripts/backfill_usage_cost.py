"""Backfill: recompute cost_usd for existing LLM usage rows.

Usage rows recorded before per-model pricing existed were saved with
cost_usd=0 (so the Usage page showed "$0 (sovereign)" even for OpenAI). This
recomputes each row's cost from its stored model + token split using the SAME
pricing the gateway now applies, so historical cost shows correctly without
waiting for new traffic.

Run inside the api/worker container:

    docker compose exec -T api python - < scripts/backfill_usage_cost.py

Safe + idempotent: it only reads stored token counts and rewrites cost_usd.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from faastlab_askai_core.db import LLMUsage, get_sessionmaker
from faastlab_askai_core.gateway.usage import estimate_cost_usd, model_cost_usd


async def main() -> int:
    sm = get_sessionmaker()
    updated = 0
    total_before = 0.0
    total_after = 0.0
    async with sm() as session:
        rows = (await session.execute(select(LLMUsage))).scalars().all()
        for row in rows:
            # Per-model price when known, else the flat fallback (0 = sovereign).
            cost = model_cost_usd(
                row.model, row.prompt_tokens or 0, row.completion_tokens or 0
            )
            if cost is None:
                cost = estimate_cost_usd(row.total_tokens or 0)
            total_before += float(row.cost_usd or 0.0)
            total_after += cost
            if abs(cost - float(row.cost_usd or 0.0)) > 1e-9:
                row.cost_usd = cost
                updated += 1
        await session.commit()
    print(
        f"Recomputed {updated} of {len(rows)} usage rows. "
        f"Total cost ${total_before:.4f} -> ${total_after:.4f}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
