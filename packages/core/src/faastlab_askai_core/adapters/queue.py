"""Queue adapter — Celery+Redis, Azure Service Bus, AWS SQS."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class QueueAdapter(Protocol):
    """Async-job dispatch.

    The default Celery+Redis implementation maps `enqueue` onto a Celery
    task signature. Cloud implementations publish a JSON message and a
    worker pool consumes it.
    """

    async def enqueue(
        self,
        task_name: str,
        payload: dict[str, Any],
        *,
        tenant_id: str,
        priority: int = 5,
    ) -> str:
        """Schedule `task_name` and return a job id."""
        ...

    async def status(self, job_id: str) -> str:
        """Return one of: pending | running | success | failed | unknown."""
        ...
