"""Tool-execution idempotency coordination."""

from __future__ import annotations

import hashlib

from agent_engine.approvals.models import ToolExecutionRecord
from agent_engine.approvals.tool_execution_repository import ToolExecutionRepository


def execution_id_for(tool_call_id: str, *, salt: str = "") -> str:
    """Return a deterministic idempotency key for one tool call."""
    digest = hashlib.sha256(f"{tool_call_id}:{salt}".encode()).hexdigest()
    return f"exec_{digest[:24]}"


class ToolExecutionManager:
    """Coordinates idempotent tool execution through an injected repository."""

    def __init__(self, *, execution_repository: ToolExecutionRepository | None = None) -> None:
        self._executions = execution_repository

    async def already_executed(self, execution_id: str) -> ToolExecutionRecord | None:
        if self._executions is None:
            return None
        record = await self._executions.get(execution_id)
        if record is not None and record.status == "succeeded":
            return record
        return None

    async def begin_execution(
        self, execution_id: str, *, tool_call_id: str, run_id: str, tool_name: str
    ) -> bool:
        """Return whether this attempt owns the key and may execute."""
        if self._executions is None:
            return True
        _, created = await self._executions.start(
            ToolExecutionRecord(
                execution_id=execution_id,
                tool_call_id=tool_call_id,
                run_id=run_id,
                tool_name=tool_name,
            )
        )
        return created

    async def finish_execution(self, execution_id: str, *, status: str, result: str) -> None:
        if self._executions is not None:
            await self._executions.complete(execution_id, status=status, result=result)
