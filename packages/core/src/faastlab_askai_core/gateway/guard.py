"""Jailbreak / prompt-injection guard — input screening at the gateway.

The gateway is the single chokepoint for LLM calls, so this is the one place to
screen a prompt for jailbreak / prompt-injection attempts BEFORE it reaches the
model. A flagged prompt is blocked (HTTP 403) and recorded, so attempts are
auditable.

Design: a `JailbreakGuard` protocol with one method, `screen(text)`. The default
`HeuristicJailbreakGuard` is rule-based — zero extra latency, fully sovereign,
and tuned for HIGH PRECISION (only clear attacks match) so it rarely blocks a
genuine compliance question. A model-based guard (e.g. Meta Prompt-Guard running
on the GPU box) can be dropped in later behind the same protocol without
touching callers — the patterns here become the cheap first line of defence.

Limitation (documented, not solved here): this screens the USER prompt. Indirect
injection — a malicious instruction embedded in an ingested document the model
later reads — is a separate problem (treat retrieved content as untrusted).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class GuardResult:
    flagged: bool
    reason: str = ""  # which rule tripped (for the audit trail / block message)
    score: float = 0.0  # 0..1 confidence; rule guard uses #matches saturating


@runtime_checkable
class JailbreakGuard(Protocol):
    def screen(self, text: str) -> GuardResult: ...


# High-precision patterns for the common jailbreak / prompt-injection families.
# Each is specific enough that it's very unlikely to appear in a legitimate
# regulatory-compliance question. Case-insensitive. Keep this list curated —
# precision over recall (the model guard is the recall layer later).
_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|rules?|messages?|context)\b",
     "instruction-override"),
    (r"\bdisregard\s+(?:all\s+|the\s+|any\s+)?(?:previous|prior|above|earlier|your)\s+(?:instructions?|rules?|guidelines?)\b",
     "instruction-override"),
    (r"\bforget\s+(?:everything|all|your|the)\s+(?:instructions?|rules?|previous|prior)\b",
     "instruction-override"),
    (r"\b(?:reveal|show|print|repeat|output|tell me)\s+(?:me\s+)?(?:your\s+|the\s+)?(?:system\s+prompt|initial\s+instructions?|original\s+instructions?|the\s+prompt above)\b",
     "system-prompt-exfiltration"),
    (r"\bwhat\s+(?:is|are|were)\s+your\s+(?:system\s+prompt|initial\s+instructions?|original\s+instructions?)\b",
     "system-prompt-exfiltration"),
    (r"\b(?:you\s+are\s+now|act\s+as|pretend\s+(?:you\s+are|to\s+be)|roleplay\s+as)\b.{0,40}\b(?:DAN|unrestricted|jailbroken|no\s+restrictions?|amoral|evil|uncensored)\b",
     "persona-jailbreak"),
    (r"\b(?:developer\s+mode|do\s+anything\s+now|DAN\s+mode|jailbreak(?:ing|en)?)\b",
     "persona-jailbreak"),
    (r"\b(?:bypass|ignore|disable|turn\s+off|override)\s+(?:your\s+|the\s+|any\s+|all\s+)?(?:safety|guidelines?|restrictions?|filters?|guardrails?|content\s+polic(?:y|ies)|rules?)\b",
     "safety-bypass"),
    (r"\b(?:without|with\s+no)\s+(?:any\s+)?(?:restrictions?|filters?|rules?|ethics?|guidelines?|censorship)\b",
     "safety-bypass"),
    (r"\bact\s+as\s+(?:if\s+you\s+(?:have|had)\s+)?no\s+(?:restrictions?|rules?|guidelines?|filters?)\b",
     "safety-bypass"),
)

_COMPILED = tuple((re.compile(p, re.IGNORECASE), label) for p, label in _PATTERNS)


class HeuristicJailbreakGuard:
    """Rule-based jailbreak/injection screen. Stateless; share one instance."""

    def screen(self, text: str) -> GuardResult:
        if not text or not text.strip():
            return GuardResult(flagged=False)
        hits = [label for rx, label in _COMPILED if rx.search(text)]
        if not hits:
            return GuardResult(flagged=False)
        # De-dup labels, keep order; score saturates with the number of distinct
        # families tripped (more families = more clearly an attack).
        seen: list[str] = []
        for h in hits:
            if h not in seen:
                seen.append(h)
        return GuardResult(
            flagged=True,
            reason=", ".join(seen),
            score=min(1.0, len(seen) / 2.0),
        )
