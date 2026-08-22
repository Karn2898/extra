"""Projection of persisted tool usage into private model context.

The LLM needs to know which tools have already run and how they ended; it does
not need the persistence record. This module owns that translation — scope,
selection, projection, and wording — so agents never format stored records
themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_engine.tool_usage.models import ToolInvocationKind, ToolInvocationStatus

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
