"""LLM-based keyphrase extraction with strict JSON output."""

from __future__ import annotations

import json

from faastlab_askai_core.adapters import LLMAdapter, LLMMessage
from faastlab_askai_core.config import Settings, get_settings
from faastlab_askai_core.factory import get_llm

from faastlab_askai_summarisation.prompts import KEYPHRASE_PROMPT


class KeyphraseExtractor:
    def __init__(
        self,
        *,
        llm: LLMAdapter | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._llm = llm or get_llm()
        self._settings = settings or get_settings()

    async def extract(self, summary: str, *, max_phrases: int = 12) -> list[str]:
        if not summary.strip():
            return []
        prompt = KEYPHRASE_PROMPT.format(summary=summary)
        response = await self._llm.complete(
            [LLMMessage(role="user", content=prompt)],
            model=self._settings.summarisation_model,
            temperature=0.0,
            max_tokens=300,
        )
        return _parse_phrases(response, max_phrases=max_phrases)


def _parse_phrases(raw: str, *, max_phrases: int) -> list[str]:
    """Tolerant parse — strip code fences, take the first JSON array."""
    text = raw.strip()
    if text.startswith("```"):
        # ```json … ``` style
        text = text.strip("`").lstrip("json").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    cleaned: list[str] = []
    for item in data:
        if isinstance(item, str):
            phrase = item.strip().strip(".,;")
            if phrase and phrase not in cleaned:
                cleaned.append(phrase)
        if len(cleaned) >= max_phrases:
            break
    return cleaned
