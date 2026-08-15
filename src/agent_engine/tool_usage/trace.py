"""Projection of persisted tool usage into the public run trace.

The API/UI trace (``RunResult.used_tools``) is a second, separate projection of
the same records — deliberately not the persistence model and not the model
context.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_engine.runtime.tool_models import ToolUsageRecord
from agent_engine.tool_usage.models import ToolInvocationKind, ToolInvocationRecord


def as_usage_records(
    records: Sequence[ToolInvocationRecord],
) -> tuple[ToolUsageRecord, ...]:
    """Map stored invocations onto the caller-facing trace, in call order.

    Child-agent invocations are left out: this trace has always meant *real
    tool/MCP calls*, and the route an orchestrator took is reported separately as
    ``visited``. They remain in the repository, where the model context uses them.
    """
    return tuple(
        ToolUsageRecord(
            name=record.call.tool_name,
            provider=record.call.provider,
            status=record.status.value,
            agent_id=record.call.agent_id,
            server_id=record.call.server_id,
            error=record.error,
        )
        for record in records
        if record.call.kind is ToolInvocationKind.TOOL
    )
