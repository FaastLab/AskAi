"""Unit tests for the #4 agentic tool-calling loop (no LLM/DB needed)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from faastlab_askai_mcp import agent as agent_mod
from faastlab_askai_mcp.agent import AgentError, AgentService


def _msg(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tool_call(call_id, name, args):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


class _FakeLLM:
    """Returns the scripted messages in order; records what it was called with."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    async def chat_with_tools(self, messages, *, tools=None, model=None, temperature=0.0, max_tokens=None):
        self.calls += 1
        return self._script.pop(0)


@pytest.fixture(autouse=True)
def _stub_tools(monkeypatch):
    monkeypatch.setattr(
        agent_mod,
        "tool_specs",
        lambda label: [
            {
                "name": "search_documents",
                "description": "search",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ],
    )
    # The agent no longer meters usage itself — the gateway does, per call. Tests
    # inject a fake `llm`, so no gateway/ledger stubbing is needed here.


async def test_agent_calls_tool_then_answers(monkeypatch) -> None:
    async def fake_dispatch(name, tenant_id, args):
        return f"RESULT[{name}:{args.get('query', '')}]"

    monkeypatch.setattr(agent_mod, "dispatch_tool", fake_dispatch)

    llm = _FakeLLM(
        [
            _msg(content="", tool_calls=[_tool_call("c1", "search_documents", {"query": "capital"})]),
            _msg(content="Firms must hold CET1 capital [FCA Handbook]."),
        ]
    )
    res = await AgentService(llm=llm).run(
        tenant_id=uuid4(), tenant_slug="acme", goal="what capital must firms hold?"
    )
    assert res.answer.startswith("Firms must hold CET1")
    assert res.iterations == 2
    assert len(res.steps) == 1
    assert res.steps[0].tool == "search_documents"
    assert "RESULT[search_documents:capital]" in res.steps[0].result_preview


async def test_agent_answers_without_tools(monkeypatch) -> None:
    monkeypatch.setattr(agent_mod, "dispatch_tool", lambda *a, **k: None)
    llm = _FakeLLM([_msg(content="Direct answer, no tools needed.")])
    res = await AgentService(llm=llm).run(tenant_id=uuid4(), tenant_slug="acme", goal="hi")
    assert res.answer == "Direct answer, no tools needed."
    assert res.steps == []
    assert res.iterations == 1


async def test_agent_feeds_tool_error_back(monkeypatch) -> None:
    async def boom_dispatch(name, tenant_id, args):
        raise RuntimeError("boom")

    monkeypatch.setattr(agent_mod, "dispatch_tool", boom_dispatch)
    llm = _FakeLLM(
        [
            _msg(content="", tool_calls=[_tool_call("c1", "search_documents", {"query": "x"})]),
            _msg(content="Sorry, the tool failed."),
        ]
    )
    res = await AgentService(llm=llm).run(tenant_id=uuid4(), tenant_slug="acme", goal="x")
    assert "tool error: boom" in res.steps[0].result_preview
    assert res.answer == "Sorry, the tool failed."


async def test_agent_step_budget_forces_wrapup(monkeypatch) -> None:
    async def fake_dispatch(name, tenant_id, args):
        return "more"

    monkeypatch.setattr(agent_mod, "dispatch_tool", fake_dispatch)
    # Every scripted msg requests another tool -> never finishes within budget.
    loop_msg = _msg(content="", tool_calls=[_tool_call("c", "search_documents", {"query": "q"})])
    llm = _FakeLLM([loop_msg, loop_msg, _msg(content="Forced final answer.")])
    res = await AgentService(llm=llm, max_steps=2).run(
        tenant_id=uuid4(), tenant_slug="acme", goal="q"
    )
    assert res.iterations == 2  # hit the budget
    assert res.answer == "Forced final answer."  # wrap-up call produced it


async def test_agent_requires_tool_capable_adapter() -> None:
    class _NoTools:
        pass

    with pytest.raises(AgentError):
        await AgentService(llm=_NoTools()).run(
            tenant_id=uuid4(), tenant_slug="acme", goal="x"
        )
