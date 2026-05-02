"""Prompts for map-reduce summarisation + keyphrase extraction."""

from __future__ import annotations

MAP_PROMPT = """\
You are summarising a slice of a regulatory document. Output a tight
3–6 sentence summary that captures the key obligations, definitions,
and exceptions in this slice. Do NOT add information that isn't here.

SLICE:
{slice}
"""

REDUCE_PROMPT = """\
Combine the slice-summaries below into a single coherent summary of the
whole document. Aim for 6–12 sentences. Lead with what the document is
(type, regulator, scope), then the most important rules / expectations,
then any notable exceptions or transitional arrangements. Use plain
English; preserve regulator terminology only when essential.

SLICE SUMMARIES:
{summaries}
"""

FOCUSED_PROMPT = """\
Summarise the document below with a focus on this question/topic:
"{query}"

Aim for 4–8 sentences. If the document barely covers the topic, say so.

DOCUMENT:
{summary}
"""

KEYPHRASE_PROMPT = """\
Extract 6–12 distinctive keyphrases from the summary below. Output as a
JSON array of strings only — no commentary. Phrases should be specific
(e.g. "CET1 capital ratio", not "capital"); regulator-relevant nouns
or noun-phrases.

SUMMARY:
{summary}
"""
