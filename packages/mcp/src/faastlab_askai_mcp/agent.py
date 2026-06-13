"""Agentic reasoning (#4) — a bounded multi-step tool-calling loop.

The model (sovereign Qwen on vLLM) is given the SAME tool catalogue the MCP
server exposes (`tool_specs`) and decides which tools to call to answer a goal.
Each requested call is executed via `dispatch_tool` and the result is fed back,
until the model produces a final grounded answer or the step budget runs out.

This turns the product from passive Q&A into *active workflow execution* — the
agent can search the corpus, pull a document, read its summary, etc., chaining
steps on its own. Bounded (max_steps) and defensive (a tool error is fed back
as text, never crashes the run). Usage is logged to the gateway ledger under
purpose="agent". Lives in the mcp package to reuse the tools without a circular
import (askai/search would otherwise import mcp).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

from faastlab_askai_core.config import get_settings
from faastlab_askai_core.exceptions import AskAiError
from faastlab_askai_core.factory import get_llm
from faastlab_askai_core.gateway import GatewayContext, record_usage, usage_from_text
from faastlab_askai_mcp.server import dispatch_tool, tool_specs

log = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """\
You are AskAi's research agent. You answer the user's goal by USING TOOLS to
gather grounded evidence from their private document corpus, then writing a
final answer.

How to work:
1. Think about what you need, then CALL a tool (search_documents, get_document,
   get_summary, list_recent). Prefer search_documents first to find relevant
   material; chain more calls if you need detail.
2. Use ONLY what the tools return — never invent facts. Cite document titles.
3. When you have enough, STOP calling tools and write the final answer:
   a 1-2 sentence direct answer, then key points, then the sources you used.
4. If the tools find nothing relevant, say so plainly and suggest what to ingest.
Be efficient — don't call tools you don't need.
"""


class AgentError(AskAiError):
    """The agent could not run (e.g. the LLM adapter lacks tool-calling)."""


@dataclass(frozen=True, slots=True)
class AgentStep:
    tool: str
    arguments: dict[str, Any]
    result_preview: str


@dataclass(frozen=True, slots=True)
class AgentResult:
    answer: str
    steps: list[AgentStep]
    iterations: int


def openai_tools(tenant_label: str) -> list[dict[str, Any]]:
    """Convert the MCP tool catalogue to OpenAI tool-calling schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["inputSchema"],
            },
        }
        for spec in tool_specs(tenant_label)
    ]


class AgentService:
    """Stateless; construct once and share."""

    def __init__(self, *, llm: Any = None, max_steps: int = 6, max_tokens: int = 1400) -> None:
        self._llm = llm or get_llm()
        self._max_steps = max_steps
        self._max_tokens = max_tokens

    async def run(
        self,
        *,
        tenant_id: UUID,
        tenant_slug: str,
        goal: str,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> AgentResult:
        if not hasattr(self._llm, "chat_with_tools"):
            raise AgentError(
                "The configured LLM adapter does not support tool-calling; "
                "the agent needs the OpenAI-compatible adapter (vLLM/OpenAI)."
            )

        tools = openai_tools(tenant_slug or "your corpus")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": goal},
        ]
        steps: list[AgentStep] = []
        t0 = perf_counter()
        answer = ""
        iterations = 0

        for i in range(self._max_steps):
            iterations = i + 1
            msg = await self._llm.chat_with_tools(
                messages, tools=tools, max_tokens=self._max_tokens
            )
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                answer = msg.content or ""
                break

            # Echo the assistant's tool-call turn back into the transcript.
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = await dispatch_tool(tc.function.name, tenant_id, args)
                except Exception as exc:
                    result = f"tool error: {exc}"
                steps.append(
                    AgentStep(
                        tool=tc.function.name,
                        arguments=args,
                        result_preview=result[:500],
                    )
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result[:6000]}
                )
        else:
            # Step budget exhausted without a final answer — force a wrap-up.
            wrap = await self._llm.chat_with_tools(
                [
                    *messages,
                    {
                        "role": "user",
                        "content": "Give your best final answer now from what you've gathered.",
                    },
                ],
                tools=None,
                max_tokens=self._max_tokens,
            )
            answer = wrap.content or answer or "(reached the step limit)"

        await self._record(tenant_id, user_id, request_id, messages, answer, t0)
        return AgentResult(answer=answer, steps=steps, iterations=iterations)

    async def _record(
        self,
        tenant_id: UUID,
        user_id: str | None,
        request_id: str | None,
        messages: list[dict[str, Any]],
        answer: str,
        t0: float,
    ) -> None:
        settings = get_settings()
        prompt_text = "\n".join(str(m.get("content") or "") for m in messages)
        await record_usage(
            GatewayContext(
                tenant_id=tenant_id,
                user_id=user_id,
                purpose="agent",
                request_id=request_id,
            ),
            usage_from_text(
                prompt=prompt_text,
                completion=answer,
                provider=settings.llm_provider,
                model=settings.llm_model,
                latency_ms=(perf_counter() - t0) * 1000,
            ),
        )
