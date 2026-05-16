"""Postgres-backed session memory for chat sessions.

Stores history as JSONB on `chat_sessions.history` keyed by `id`.
The shape is a list of {role, content} dicts (LLMMessage-compatible).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from faastlab_askai_core.adapters import LLMMessage
from faastlab_askai_core.db import ChatSession, get_sessionmaker

_MAX_TURNS = 20  # cap context window growth — older turns are dropped


class SessionMemory:
    """Read/write a session's chat history."""

    def __init__(self, *, max_turns: int = _MAX_TURNS) -> None:
        self._sessionmaker = get_sessionmaker()
        self._max_turns = max_turns

    async def load(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID | None,
    ) -> tuple[UUID, list[LLMMessage]]:
        """Return (session_id, history). Creates a new session if none given."""
        if session_id is None:
            return uuid4(), []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(ChatSession).where(
                    (ChatSession.id == session_id)
                    & (ChatSession.tenant_id == tenant_id)
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return session_id, []
            messages = [
                LLMMessage(role=m["role"], content=m["content"])
                for m in (row.history or {}).get("messages", [])
            ]
            return row.id, messages

    async def append(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        user_id: str,
        question: str,
        answer: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> None:
        """Persist one Q/A turn. Creates the row on first call.

        Citations are stored on the assistant turn so the UI can re-hydrate
        them when a user re-opens the session from the sidebar.
        """
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(ChatSession).where(
                    (ChatSession.id == session_id)
                    & (ChatSession.tenant_id == tenant_id)
                )
            )
            row = result.scalar_one_or_none()
            now = datetime.now(UTC)
            if row is None:
                row = ChatSession(
                    id=session_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    title=question[:200],
                    history={"messages": []},
                )
                session.add(row)

            messages: list[dict[str, Any]] = list((row.history or {}).get("messages", []))
            messages.append({"role": "user", "content": question, "ts": now.isoformat()})
            messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "ts": now.isoformat(),
                    "citations": citations or [],
                }
            )
            row.history = {"messages": messages[-self._max_turns * 2 :]}
            await session.commit()
