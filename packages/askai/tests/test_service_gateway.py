"""AskAiService routes generation through the AIGateway (the chokepoint).

Mocks search/gateway/memory so no DB or model is needed — verifies the
gateway is called with assembled RAG messages, and that the no-context path
refuses WITHOUT calling the gateway.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from faastlab_askai_askai.prompts import REFUSAL_NO_CONTEXT
from faastlab_askai_askai.service import AskAiService
from faastlab_askai_search.retrievers.base import RetrievedChunk


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        tenant_id=uuid4(),
        document_title="FCA Handbook",
        content="Firms must hold CET1 capital.",
        score=0.9,
        rank=1,
    )


class _FakeSearch:
    def __init__(self, hits):
        self._hits = hits

    async def search(self, *, tenant_id, query, k, filters=None, rerank=True, meter=True):
        return SimpleNamespace(hits=self._hits, confidence=0.5, latency_ms=1.0, query=query)


class _FakeGateway:
    def __init__(self):
        self.completed = False
        self.streamed = False
        self.seen_messages = None

    async def complete(self, ctx, messages, *, temperature=0.0, max_tokens=None):
        self.completed = True
        self.seen_messages = messages
        return SimpleNamespace(text="Firms must hold CET1 capital [1].")

    async def stream(self, ctx, messages, *, temperature=0.0, max_tokens=None):
        self.streamed = True
        self.seen_messages = messages
        for tok in ("Firms ", "must [1]"):
            yield tok


class _FakeMemory:
    async def load(self, *, tenant_id, session_id):
        return (uuid4(), [])

    async def append(self, **kwargs):
        return None


def _service(hits, gw):
    return AskAiService(search=_FakeSearch(hits), gateway=gw, memory=_FakeMemory())


async def test_ask_routes_through_gateway() -> None:
    gw = _FakeGateway()
    out = await _service([_chunk()], gw).ask(
        tenant_id=uuid4(), user_id="u1", question="What capital must firms hold?"
    )
    assert gw.completed is True
    assert "CET1" in out.answer
    assert out.chunks_used == 1
    # The gateway received assembled RAG messages (system + user), not raw text.
    assert gw.seen_messages and gw.seen_messages[0].role == "system"


async def test_ask_no_context_refuses_without_gateway() -> None:
    gw = _FakeGateway()
    out = await _service([], gw).ask(tenant_id=uuid4(), user_id="u1", question="x")
    assert gw.completed is False  # no model call when there's nothing to ground on
    assert out.answer == REFUSAL_NO_CONTEXT


async def test_stream_routes_through_gateway() -> None:
    gw = _FakeGateway()
    events = [
        e
        async for e in _service([_chunk()], gw).stream_ask(
            tenant_id=uuid4(), user_id="u1", question="q"
        )
    ]
    kinds = [e["event"] for e in events]
    assert gw.streamed is True
    assert kinds[0] == "retrieve" and kinds[-1] == "done"
    tokens = "".join(e["text"] for e in events if e["event"] == "token")
    assert tokens == "Firms must [1]"


async def test_stream_no_context_refuses_without_gateway() -> None:
    gw = _FakeGateway()
    events = [
        e
        async for e in _service([], gw).stream_ask(
            tenant_id=uuid4(), user_id="u1", question="q"
        )
    ]
    assert gw.streamed is False
    token_text = "".join(e["text"] for e in events if e["event"] == "token")
    assert token_text == REFUSAL_NO_CONTEXT
