"""Per-run execution metadata projected into model and reporting scopes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from agent_engine.runtime.hooks import current_run_context
from agent_engine.tool_usage.context_models import ToolUsageScope
from agent_engine.tool_usage.context_provider import ToolUsageContextProvider


def current_usage_scope(agent_id: str | None = None) -> ToolUsageScope:
    """Return the ambient conversation/run scope used for tool-usage reporting."""
    ctx = current_run_context.get()
    if ctx is None:
        return ToolUsageScope(agent_id=agent_id)
    return ToolUsageScope(
        run_id=ctx.run_id,
        conversation_id=ctx.conversation_id,
        agent_id=agent_id,
    )


ExecutionContextRefresher = Callable[[], Awaitable[str | None]]


def execution_context_refresher(
    provider: ToolUsageContextProvider,
    agent_id: str,
) -> ExecutionContextRefresher:
    """Bind a usage provider to one agent's ambient scope, ready to re-read."""

    async def refresh() -> str | None:
        context = await provider.get(current_usage_scope(agent_id))
        return context.render()

    return refresh
