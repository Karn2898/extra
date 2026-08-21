"""The engine's own read-only tool for reporting what has already executed.

An orchestrator's children are bound to it as tools, so asked "which tools have
run?" a model answers from that list and names a child agent — a claim no system
instruction reliably corrected. Giving it a tool turns the question into a tool
call whose result comes from the usage repository, which the model cannot
contradict from its own bindings.

The tool performs no side effect: it reads execution metadata and returns text.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, StructuredTool

from agent_engine.engine.langgraph.execution.execution_context import current_usage_scope
from agent_engine.logging_config import log
from agent_engine.tool_usage.context_models import (
    EXECUTION_RECORD_UNAVAILABLE,
    format_executed_tools,
)
from agent_engine.tool_usage.context_provider import ToolUsageContextProvider

logger = logging.getLogger(__name__)

EXECUTED_TOOLS_TOOL_NAME = "list_executed_tools"

_DESCRIPTION = (
    "List the tools that have actually been executed so far in this conversation, "
    "with the agent that ran each one and its outcome. Call this whenever the user "
    "asks which tools have run, what has been done, or whether an action already "
    "happened. The result is authoritative execution metadata: answer from it, not "
    "from the agents in your own tool list."
)


def build_executed_tools_tool(provider: ToolUsageContextProvider, agent_id: str) -> BaseTool:
    """Bind the usage provider into a no-argument reporting tool."""

    async def list_executed_tools() -> str:
        scope = current_usage_scope(agent_id)
        try:
            context = await provider.get_executed_tools(scope)
        except Exception as exc:
            # Never raise out of a tool the model called, and never let a read
            # failure be reported as "nothing has run" — that would invite a
            # repeat of an action that already took effect.
            log(
                logger,
                logging.WARNING,
                "execution record unavailable",
                agent=agent_id,
                run_id=scope.run_id,
                conversation_id=scope.conversation_id,
                error=type(exc).__name__,
            )
            return EXECUTION_RECORD_UNAVAILABLE
        return format_executed_tools(context)

    return StructuredTool.from_function(
        coroutine=list_executed_tools,
        name=EXECUTED_TOOLS_TOOL_NAME,
        description=_DESCRIPTION,
    )
