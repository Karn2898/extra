"""Turns tool-execution events into persisted usage records."""

from __future__ import annotations

import logging

from agent_engine.logging_config import log
from agent_engine.tool_usage.models import (
    ToolCallIdentity,
    ToolInvocationRecord,
    ToolInvocationStatus,
)
from agent_engine.tool_usage.repository import ToolUsageRepository

logger = logging.getLogger(__name__)

_ERROR_MAX_CHARS = 200


class ToolUsageTracker:
    """Records what happened to a tool invocation, and nothing else.

    It does not decide whether a tool may run, execute anything, build prompts,
    or choose a backend: it maps one execution event onto one domain record and
    hands it to the injected repository. Holding no per-run state, a single
    instance is shared by every agent in the engine.

    Failure policy: recording is observability, not the tool's contract, so a
    repository error is logged at WARNING with the invocation's identity and
    swallowed. A metadata write must never turn a completed tool call into a
    failed one, nor mask the tool's own error. The cost is a trace that may be
    missing an entry the log names explicitly.
    """

    def __init__(self, repository: ToolUsageRepository) -> None:
        self._repository = repository

    async def record_success(self, call: ToolCallIdentity) -> None:
        await self._record(ToolInvocationRecord(call=call, status=ToolInvocationStatus.SUCCEEDED))

    async def record_failure(self, call: ToolCallIdentity, *, error: str) -> None:
        await self._record(
            ToolInvocationRecord(
                call=call,
                status=ToolInvocationStatus.FAILED,
                error=error[:_ERROR_MAX_CHARS],
            )
        )

    async def record_denied(self, call: ToolCallIdentity) -> None:
        await self._record(ToolInvocationRecord(call=call, status=ToolInvocationStatus.DENIED))

    async def _record(self, record: ToolInvocationRecord) -> None:
        try:
            await self._repository.record(record)
        except Exception as exc:
            log(
                logger,
                logging.WARNING,
                "tool usage not recorded",
                run_id=record.call.run_id,
                agent=record.call.agent_id,
                tool=record.call.tool_name,
                tool_call_id=record.call.tool_call_id,
                status=record.status.value,
                error=type(exc).__name__,
            )
