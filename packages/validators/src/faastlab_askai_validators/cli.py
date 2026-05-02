"""CLI: validate a PDF / DOCX / text report against a tenant's corpus."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from faastlab_askai_core.db import Tenant, get_sessionmaker
from faastlab_askai_indexing.parsers.router import detect_content_type, get_parser

from faastlab_askai_validators.pipeline import ValidatorPipeline


async def _resolve_tenant(slug_or_id: str) -> UUID:
    try:
        return UUID(slug_or_id)
    except ValueError:
        pass
    sm = get_sessionmaker()
    async with sm() as session:
        result = await session.execute(
            select(Tenant.id).where(Tenant.slug == slug_or_id)
        )
        row = result.scalar_one_or_none()
    if row is None:
        raise SystemExit(f"No tenant matches: {slug_or_id!r}")
    return row


async def main_async(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="askai-validate")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--report", required=True, help="Path to PDF/DOCX/txt report")
    args = parser.parse_args(argv)

    tenant_id = await _resolve_tenant(args.tenant)
    path = Path(args.report)
    data = path.read_bytes()
    content_type = detect_content_type(path.name)

    if content_type.startswith("text/plain") or path.suffix.lower() == ".txt":
        report_text = data.decode("utf-8", errors="replace")
    else:
        parser_obj = get_parser(content_type)
        parsed = parser_obj.parse(data, filename=path.name)
        report_text = parsed.text

    pipeline = ValidatorPipeline()
    result = await pipeline.validate_report(
        tenant_id=tenant_id, report_text=report_text
    )

    light = {"green": "🟢", "amber": "🟡", "red": "🔴"}.get(result.overall, "?")
    print(f"\n{light}  {result.summary}")
    print(f"   total claims: {result.total_claims}  "
          f"(supported {result.supported} / contradicted {result.contradicted} / "
          f"unsupported {result.unsupported})\n")
    for v in result.claims:
        marker = {"supported": "✓", "contradicted": "✗", "unsupported": "?"}.get(
            v.verdict, "?"
        )
        print(f"  [{marker}] {v.claim}")
        print(f"        {v.rationale}")
        for c in v.citations[:2]:
            print(f"        · {c.document_title}, page {c.page_number}")
        print()
    return 0 if result.overall != "red" else 2


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
