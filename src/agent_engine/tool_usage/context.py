"""Projection of persisted tool usage into private model context.

The LLM needs to know which tools have already run and how they ended; it does
not need the persistence record. This module owns that translation — scope,
selection, projection, and wording — so agents never format stored records
themselves.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from agent_engine.logging_config import log
from agent_engine.tool_usage.models import (
    ToolInvocationKind,
    ToolInvocationRecord,
    ToolInvocationStatus,
)
from agent_engine.tool_usage.repository import ToolUsageRepository

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 50
DEFAULT_REPORT_MAX_ENTRIES = 200

_HEADER = (
    "## Execution record for this conversation\n"
    "Internal execution metadata, not chat history. Some of the tools bound to "
    "you are other agents: calling one delegates the work, it does not perform "
    "it. This record separates the two. Reason with it, do not redo work it "
    "shows as done, and do not restate it unless it is relevant."
)

_TOOLS_HEADING = (
    "### Tools executed\n"
    "The real actions that ran, as `agent: tool`. These — and only these — are "
    "the tools that have run in this conversation; answer with these names when "
    "the user asks which tools ran, even if the tool is not one of your own."
)

_DELEGATIONS_HEADING = (
    "### Agents delegated to\n"
    "Routing only, as `agent -> agent`. An agent is not a tool: never name one "
    "of these when asked which tools ran."
)

_TRUNCATED = "(Older entries are not shown; this record is not complete.)"


@dataclass(frozen=True)
class ToolUsageScope:
    """Who is asking, and about which conversation and run.

    The ids come from the ambient run context; ``agent_id`` names the caller, so
    the projection can tell the asker's own invocations from everyone else's.
    """

    run_id: str | None = None
    conversation_id: str | None = None
    agent_id: str | None = None


@dataclass(frozen=True)
class ToolUsageEntry:
    """The few facts the model is given about one prior invocation."""

    agent_id: str
    tool_name: str
    status: str
    kind: ToolInvocationKind = ToolInvocationKind.TOOL


@dataclass(frozen=True)
class ToolUsageContext:
    """What the model may know about tool usage so far, grouped when rendered.

    A value object distinct from the persistence record: no timestamps, ids,
    arguments, results, or error text cross this boundary.
    """

    entries: tuple[ToolUsageEntry, ...] = ()
    truncated: bool = False
    """Older invocations were dropped to bound the size, and are not shown."""

    @property
    def is_empty(self) -> bool:
        return not self.entries

    def render(self) -> str | None:
        """Render the internal context block, or ``None`` when there is nothing
        to say — so an unused conversation costs no tokens at all.

        Tools and delegations are rendered as separate, labelled sections. They
        are different kinds of action, and a model asked "which tools did you
        run?" must not answer with the name of a child agent.
        """
        if self.is_empty:
            return None
        sections = [
            section
            for section in (self._tool_section(), self._delegation_section())
            if section is not None
        ]
        if self.truncated:
            sections.append(_TRUNCATED)
        return "\n\n".join([_HEADER, *sections])

    def _tool_section(self) -> str | None:
        tools = [e for e in self.entries if e.kind is ToolInvocationKind.TOOL]
        if not tools:
            return None
        by_agent: dict[str, list[ToolUsageEntry]] = {}
        for entry in tools:
            by_agent.setdefault(entry.agent_id, []).append(entry)
        blocks = [
            "\n".join([f"{agent}:", *(f"- {e.tool_name} [{e.status}]" for e in entries)])
            for agent, entries in by_agent.items()
        ]
        return "\n\n".join([_TOOLS_HEADING, *blocks])

    def _delegation_section(self) -> str | None:
        delegations = [e for e in self.entries if e.kind is ToolInvocationKind.AGENT]
        if not delegations:
            return None
        lines = [f"- {e.agent_id} -> {e.tool_name}{self._failure(e)}" for e in delegations]
        return "\n".join([_DELEGATIONS_HEADING, *lines])

    @staticmethod
    def _failure(entry: ToolUsageEntry) -> str:
        """Routing that worked is just a path; routing that did not is news."""
        return "" if entry.status == ToolInvocationStatus.SUCCEEDED.value else f" [{entry.status}]"


EMPTY_CONTEXT = ToolUsageContext()

_NOTHING_EXECUTED = "No tools have been executed in this conversation yet."

EXECUTION_RECORD_UNAVAILABLE = (
    "The execution record could not be read right now, so what has already run is "
    "unknown. Do not assume nothing has run, and do not repeat an action that may "
    "already have taken effect; say the record is unavailable."
)


def format_executed_tools(context: ToolUsageContext) -> str:
    """Render executed tools as an answerable list, for a tool result.

    A second model-facing wording, kept beside the first so the vocabulary of
    execution metadata lives in one module rather than in whatever calls it.
    """
    if context.is_empty:
        return _NOTHING_EXECUTED
    lines = [f"- {e.agent_id}: {e.tool_name} [{e.status}]" for e in context.entries]
    body = ["Tools executed in this conversation, oldest first:", *lines]
    if context.truncated:
        body.append(_TRUNCATED)
    return "\n".join(body)


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

    async def get(
        self,
        scope: ToolUsageScope,
        *,
        already_visible: frozenset[str] = frozenset(),
    ) -> ToolUsageContext:
        """Return the usage context for ``scope``.

        The conversation is preferred when the caller has one, so a later turn
        still knows what earlier turns did; a run started outside a conversation
        falls back to its own run. A scope with neither id — a caller running
        outside any registered run — yields empty context rather than an error.

        ``already_visible`` names the tools the caller has itself invoked in the
        turn it is about to send. Those invocations reach the model in full
        through the normal tool protocol (``AIMessage`` + ``ToolMessage``), so
        repeating them here would spend tokens saying less.
        """
        try:
            records = await self._load(scope)
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
        return self._project(records, scope, already_visible)

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
        records = [r for r in await self._load(scope) if r.call.kind is ToolInvocationKind.TOOL]
        return self._bounded(records, self._report_max_entries)

    async def _load(self, scope: ToolUsageScope) -> Sequence[ToolInvocationRecord]:
        if scope.conversation_id:
            return await self._repository.list_for_conversation(scope.conversation_id)
        if scope.run_id:
            return await self._repository.list_for_run(scope.run_id)
        return ()

    def _project(
        self,
        records: Sequence[ToolInvocationRecord],
        scope: ToolUsageScope,
        already_visible: frozenset[str],
    ) -> ToolUsageContext:
        wanted = [
            r
            for r in records
            if self._is_included(r) and not self._is_visible(r, scope, already_visible)
        ]
        return self._bounded(wanted, self._max_entries)

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

    def _is_included(self, record: ToolInvocationRecord) -> bool:
        return self._include_delegations or record.call.kind is ToolInvocationKind.TOOL

    @staticmethod
    def _is_visible(
        record: ToolInvocationRecord,
        scope: ToolUsageScope,
        already_visible: frozenset[str],
    ) -> bool:
        """Whether the caller's own turn already shows the model this invocation.

        Only the asker's own calls, in the run it is currently executing, can be
        in its message list — another agent's call, or the same agent's call in
        an earlier run or an earlier node entry, is not.
        """
        call = record.call
        return (
            call.tool_name in already_visible
            and call.agent_id == scope.agent_id
            and call.run_id == scope.run_id
        )
