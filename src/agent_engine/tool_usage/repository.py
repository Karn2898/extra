"""Abstract persistence contract for tool usage.

The engine depends only on this explicit abstract base class. A shared
deployment supplies a distributed adapter with the same contract; nothing in the
agents, nodes, or tool-execution path changes when it does.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from agent_engine.tool_usage.models import ToolInvocationKind, ToolInvocationRecord


class ToolUsageRepository(ABC):
    """Persistence contract for observed tool usage, the source of truth.

    A record is identified by ``(run_id, tool_call_id)``. Implementations must:

    * treat ``record`` as an idempotent upsert on that identity, so a resumed or
      replayed invocation updates its record instead of adding a second one;
    * keep first-seen order, which is chronological call order, within both
      scopes;
    * return snapshots that no later write mutates;
    * when ``limit`` is supplied, return the latest records in chronological
      order (not reverse order), after applying the optional ``kind`` filter.

    Scopes are isolated: a listing never returns a record from another run or
    another conversation, and an unknown id yields no records. A record whose
    identity carries no ``conversation_id`` is reachable by run only.
    """

    @abstractmethod
    async def record(self, record: ToolInvocationRecord) -> None:
        """Store the outcome of one logical tool invocation."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_run(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        kind: ToolInvocationKind | None = None,
    ) -> Sequence[ToolInvocationRecord]:
        """Return this run's records in call order (empty when unknown)."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        kind: ToolInvocationKind | None = None,
    ) -> Sequence[ToolInvocationRecord]:
        """Return every run's records for this conversation, in call order."""
        raise NotImplementedError
