"""POST /v1/agent — agentic reasoning (#4).

Runs a bounded multi-step tool-calling loop: the sovereign LLM decides which
corpus tools to call, executes them, and returns a grounded answer plus the
step trace. Governed like /v1/ask (trial + quota + policy, purpose="agent")
and metered in the usage ledger.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from faastlab_askai_api.audit_helper import record_action
from faastlab_askai_api.middleware.policy import enforce_policy
from faastlab_askai_api.middleware.quota import enforce_quota
from faastlab_askai_api.middleware.trial import require_active_trial_or_subscription
from faastlab_askai_api.routes.ask import _require_byok_if_configured
from faastlab_askai_core.adapters import Principal
from faastlab_askai_mcp.agent import AgentError, AgentService

router = APIRouter(tags=["agent"])
_agent = AgentService()


class AgentRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)


class AgentStepView(BaseModel):
    tool: str
    arguments: dict
    result_preview: str


class AgentResponse(BaseModel):
    answer: str
    iterations: int
    steps: list[AgentStepView]


@router.post("/agent", response_model=AgentResponse)
async def agent(
    body: AgentRequest,
    request: Request,
    principal: Principal = Depends(require_active_trial_or_subscription),
    _quota: Principal = Depends(enforce_quota("agent")),
    _policy: Principal = Depends(enforce_policy("agent")),
) -> AgentResponse:
    _require_byok_if_configured()
    request_id = request.headers.get("x-request-id") or uuid4().hex
    try:
        result = await _agent.run(
            tenant_id=principal.tenant_id,
            tenant_slug=principal.tenant_slug,
            goal=body.goal,
            user_id=principal.user_id,
            request_id=request_id,
        )
    except AgentError as exc:
        # 501: the deployment's LLM isn't tool-call-enabled (vLLM flags).
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)
        ) from exc

    await record_action(
        principal=principal,
        action="agent",
        resource="/v1/agent",
        query=body.goal,
        response_summary=result.answer[:600],
        sources=[{"tool": s.tool, "arguments": s.arguments} for s in result.steps],
        extra={"request_id": request_id, "iterations": result.iterations},
    )
    return AgentResponse(
        answer=result.answer,
        iterations=result.iterations,
        steps=[
            AgentStepView(
                tool=s.tool, arguments=s.arguments, result_preview=s.result_preview
            )
            for s in result.steps
        ],
    )
