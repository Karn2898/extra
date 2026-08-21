"""Shared tool-usage tracking: what happened to every tool call in a run.

The subsystem answers one question — *which agent invoked which tool during
which run, and with what outcome* — and keeps its two audiences apart:

* :mod:`models` — the domain record and the ``run → agent → tool call`` identity.
* :mod:`repository` — the persistence port; the source of truth.
* :mod:`in_memory` — the process-local adapter for development and tests.
* :mod:`tracker` — writes execution outcomes through the port.
* :mod:`context_provider` — projects persisted usage into private model context.
* :mod:`trace` — projects persisted usage into the public run trace.

It makes no authorization decisions; whether a call may run belongs to
:mod:`agent_engine.approvals`. The two subsystems share identifiers (``run_id``,
``tool_call_id``, agent, tool) without sharing responsibilities.
"""

from __future__ import annotations

from agent_engine.tool_usage.context_models import (
    ToolUsageContext,
    ToolUsageEntry,
    ToolUsageScope,
)
from agent_engine.tool_usage.context_provider import ToolUsageContextProvider
from agent_engine.tool_usage.in_memory import InMemoryToolUsageRepository
from agent_engine.tool_usage.models import (
    ToolCallIdentity,
    ToolInvocationKind,
    ToolInvocationRecord,
    ToolInvocationStatus,
    stable_tool_call_id,
)
from agent_engine.tool_usage.repository import ToolUsageRepository
from agent_engine.tool_usage.trace import as_usage_records
from agent_engine.tool_usage.tracker import ToolUsageTracker

__all__ = [
    "InMemoryToolUsageRepository",
    "ToolCallIdentity",
    "ToolInvocationKind",
    "ToolInvocationRecord",
    "ToolInvocationStatus",
    "ToolUsageContext",
    "ToolUsageContextProvider",
    "ToolUsageEntry",
    "ToolUsageRepository",
    "ToolUsageScope",
    "ToolUsageTracker",
    "as_usage_records",
    "stable_tool_call_id",
]
