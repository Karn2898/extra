"""Read persisted tool usage and project it into private model context."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from agent_engine.logging_config import log
from agent_engine.tool_usage.context_models import (
    EMPTY_CONTEXT,
    ToolUsageContext,
    ToolUsageEntry,
    ToolUsageScope,
)
from agent_engine.tool_usage.models import (
    ToolInvocationKind,
    ToolInvocationRecord,
)
from agent_engine.tool_usage.repository import ToolUsageRepository

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 50
DEFAULT_REPORT_MAX_ENTRIES = 200


class ToolUsageContextProvider:
    """Reads persisted usage for a scope and projects it for the model.

    The single seam where context policy lives: which scope is consulted, which
    invocations are shown, how many, and in what shape. Changing that policy
    touches this class only — agents ask for a scope's context and pass the
    result on. It never executes tools and never writes.

    ``max_entries`` and ``report_max_entries`` bound prompt growth on a long
    conversation by keeping the most recent invocations; a trimmed context says
    so rather than passing itself off as complete.

    The two read paths degrade differently on purpose. :meth:`get` supplements a
    turn, so a read failure degrades to empty context (logged) rather than
    failing the run — an empty block is what an early conversation looks like
    anyway. :meth:`get_executed_tools` answers a direct question, where "empty"
    would be a false statement that nothing ran, so it propagates the failure
    and lets its caller say the record is unavailable.

    ``include_delegations`` reports routing in its own labelled section. It is on
    by default so an orchestrator sees the whole picture — its own children are
    bound to it as tools, so a record that mentioned neither would leave it
    reasoning from its tool binding alone. Turn it off for a deployment that
    wants the model to see executed tools only.
    """

    def __init__(
        self,
        repository: ToolUsageRepository,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        report_max_entries: int = DEFAULT_REPORT_MAX_ENTRIES,
        include_delegations: bool = True,
    ) -> None:
        if max_entries <= 0 or report_max_entries <= 0:
            raise ValueError("entry limits must be positive")
        self._repository = repository
        self._max_entries = max_entries
        self._report_max_entries = report_max_entries
        self._include_delegations = include_delegations

    async def get(self, scope: ToolUsageScope) -> ToolUsageContext:
        """Return the usage context for ``scope``.

        The conversation is preferred when the caller has one, so a later turn
        still knows what earlier turns did; a run started outside a conversation
        falls back to its own run. A scope with neither id — a caller running
        outside any registered run — yields empty context rather than an error.

        The repository is always read with ``max_entries + 1``. The extra row is
        used only to tell whether the rendered context is truncated.
        """
        try:
            kind = None if self._include_delegations else ToolInvocationKind.TOOL
            records = await self._load(scope, limit=self._max_entries + 1, kind=kind)
        except Exception as exc:
            log(
                logger,
                logging.WARNING,
                "tool usage context unavailable",
                run_id=scope.run_id,
                conversation_id=scope.conversation_id,
                error=type(exc).__name__,
            )
            return EMPTY_CONTEXT
        return self._bounded(records, self._max_entries)

    async def get_executed_tools(self, scope: ToolUsageScope) -> ToolUsageContext:
        """Every tool executed in ``scope``, for an explicit question about them.

        Unlike :meth:`get`, the turn's own visible calls are not filtered out —
        this answers "what has run?", not "what does this turn still need to be
        told?". Delegations are never included: they are routing, and the
        question is about tools.

        A repository failure propagates. Reporting "nothing has run" when the
        record cannot be read would invite an agent to repeat an action that
        already took effect.
        """
        records = await self._load(
            scope,
            limit=self._report_max_entries + 1,
            kind=ToolInvocationKind.TOOL,
        )
        return self._bounded(records, self._report_max_entries)

    async def _load(
        self,
        scope: ToolUsageScope,
        *,
        limit: int,
        kind: ToolInvocationKind | None,
    ) -> Sequence[ToolInvocationRecord]:
        if scope.conversation_id:
            return await self._repository.list_for_conversation(
                scope.conversation_id, limit=limit, kind=kind
            )
        if scope.run_id:
            return await self._repository.list_for_run(scope.run_id, limit=limit, kind=kind)
        return ()

    @staticmethod
    def _bounded(records: Sequence[ToolInvocationRecord], limit: int) -> ToolUsageContext:
        """Project the most recent ``limit`` records, saying so when older ones
        were dropped — a partial record must not read as a complete one."""
        return ToolUsageContext(
            entries=tuple(
                ToolUsageEntry(
                    agent_id=record.call.agent_id,
                    tool_name=record.call.tool_name,
                    status=record.status.value,
                    kind=record.call.kind,
                )
                for record in records[-limit:]
            ),
            truncated=len(records) > limit,
        )
