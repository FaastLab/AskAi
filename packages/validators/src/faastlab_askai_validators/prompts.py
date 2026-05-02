"""Prompts: claim extraction + per-claim adjudication."""

from __future__ import annotations

CLAIM_EXTRACTION_PROMPT = """\
You are reviewing a regulatory report for compliance against a corpus
of authoritative rules. Extract the report's distinct factual or
compliance-relevant CLAIMS — short statements the firm asserts that a
reviewer would want to verify.

Output a JSON array of strings, max 25 claims. No commentary, no code
fences. Each claim should be self-contained (no pronouns referring to
unstated subjects). Phrase claims in plain English.

REPORT:
{report}
"""

ADJUDICATE_PROMPT = """\
You are checking ONE claim against authoritative regulatory context.
Decide:

- "supported"   — the claim is consistent with the context
- "contradicted" — the claim is inconsistent with the context
- "unsupported" — context doesn't address the claim either way

Reply as a SINGLE JSON object with these keys exactly:
{{
  "verdict": "supported" | "contradicted" | "unsupported",
  "rationale": "1–3 sentence justification",
  "evidence": [<integer indices into the context list>]
}}

CLAIM:
{claim}

CONTEXT:
{context}
"""
