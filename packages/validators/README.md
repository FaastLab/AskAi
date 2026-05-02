# `faastlab-askai-validators`

Phase 10 — implemented.

A reference agent built **on top of** the AskAi platform — demonstrating
how third parties can build domain-specific compliance / validation
agents using the search + ask APIs.

## What it does

Takes a regulatory report (PDF / DOCX / txt), extracts factual claims
the firm has made, retrieves the most authoritative corpus context for
each claim from a chosen tenant, and adjudicates each claim as
**supported / contradicted / unsupported** with citations back to the
source document and page.

Aggregates into a traffic-light verdict:

- 🟢 **green** — no contradictions, ≥ 70 % supported
- 🟡 **amber** — no contradictions, but lots of unsupported claims
- 🔴 **red** — at least one claim contradicts the corpus

## Use it

```bash
make validate TENANT=demo-public REPORT=./my-firm-icaap-2025.pdf
# or directly:
uv run python -m faastlab_askai_validators.cli \
  --tenant demo-public --report ./my-firm-icaap-2025.pdf
```

## How it's built (look at the source)

`packages/validators/src/faastlab_askai_validators/pipeline.py` is
intentionally short — under 200 lines of Python. The point is to show
that AskAi's adapters + search + LLM make it cheap to build a
specialised agent without reinventing the platform.
