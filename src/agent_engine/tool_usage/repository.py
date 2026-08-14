"""Abstract persistence contract for tool usage.

The engine depends only on this ``Protocol`` (Dependency Inversion). A shared
deployment supplies a distributed adapter with the same contract; nothing in the
agents, nodes, or tool-execution path changes when it does.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from agent_engine.tool_usage.models import ToolInvocationRecord


@runtime_checkable
class ToolUsageRepository(Protocol):
    """Persistence contract for observed tool usage, the source of truth.

    A record is identified by ``(run_id, tool_call_id)``. Implementations must:

    * treat ``record`` as an idempotent upsert on that identity, so a resumed or
      replayed invocation updates its record instead of adding a second one;
    * keep first-seen order, which is chronological call order, within both
      scopes;
    * return snapshots that no later write mutates.

    Scopes are isolated: a listing never returns a record from another run or
    another conversation, and an unknown id yields no records. A record whose
    identity carries no ``conversation_id`` is reachable by run only.
    """

    async def record(self, record: ToolInvocationRecord) -> None:
        """Store the outcome of one logical tool invocation."""
        ...

    async def list_for_run(self, run_id: str) -> Sequence[ToolInvocationRecord]:
        """Return this run's records in call order (empty when unknown)."""
        ...

    async def list_for_conversation(self, conversation_id: str) -> Sequence[ToolInvocationRecord]:
        """Return every run's records for this conversation, in call order."""
        ...
