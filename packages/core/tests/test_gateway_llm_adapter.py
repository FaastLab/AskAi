"""GatewayLLMAdapter routes the LLMAdapter surface through the gateway.

A fake AIGateway captures the GatewayContext so we confirm the adapter binds the
right (tenant_id, purpose) and forwards complete / chat_with_tools — the seam
that makes summarisation/validators/agent governed without changing their code.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.gateway import GatewayLLMAdapter


class _FakeGateway:
    def __init__(self) -> None:
        self.complete_ctx = None
        self.tools_ctx = None

    async def complete(self, ctx, messages, *, temperature=0.0, max_tokens=None):
        self.complete_ctx = ctx
        return SimpleNamespace(text="ANSWER")

    async def complete_with_tools(self, ctx, messages, *, tools=None, temperature=0.0, max_tokens=None):
        self.tools_ctx = ctx
        return SimpleNamespace(content="TOOL-ANSWER", tool_calls=None)


async def test_complete_binds_context_and_returns_text() -> None:
    gw = _FakeGateway()
    tid = uuid4()
    adapter = GatewayLLMAdapter(tenant_id=tid, purpose="validate", user_id="u1", gateway=gw)

    text = await adapter.complete([LLMMessage(role="user", content="hi")])

    assert text == "ANSWER"
    assert gw.complete_ctx.tenant_id == tid
    assert gw.complete_ctx.purpose == "validate"
    assert gw.complete_ctx.user_id == "u1"


async def test_chat_with_tools_routes_through_gateway() -> None:
    gw = _FakeGateway()
    tid = uuid4()
    adapter = GatewayLLMAdapter(tenant_id=tid, purpose="agent", gateway=gw)

    msg = await adapter.chat_with_tools([{"role": "user", "content": "go"}], tools=[])

    assert msg.content == "TOOL-ANSWER"
    assert gw.tools_ctx.purpose == "agent"
    assert gw.tools_ctx.tenant_id == tid
