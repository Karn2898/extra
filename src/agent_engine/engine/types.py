from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agent_engine.approvals.models import RunStatus
from agent_engine.runtime.tool_models import ToolProviderName, ToolUsageRecord


class ChatRole(StrEnum):
    """Roles accepted as structured conversation history by the engine."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatMessage:
    """One prior conversational turn supplied to a stateless engine run."""

    role: ChatRole
    content: str


@dataclass(frozen=True)
class PendingApproval:
    """A run suspended awaiting a human decision on a tool call.

    Carries only sanitized, non-secret fields — safe to return to a UI.
    """

    run_id: str
    approval_id: str
    agent_id: str
    tool_name: str
    description: str
    provider: ToolProviderName = "local"
    server_id: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunResult:
    """The outcome of one run: the route taken, the answer, and the tools
    observed along the way.

    When ``status`` is ``PENDING_APPROVAL`` the run is suspended at an approval
    interrupt, ``pending_approval`` is populated, and ``answer`` is empty.
    """

    system_name: str
    visited: list[str]
    answer: str
    used_tools: tuple[ToolUsageRecord, ...] = field(default_factory=tuple)
    input_tokens: int | None = None
    output_tokens: int | None = None
    status: RunStatus = RunStatus.COMPLETED
    pending_approval: PendingApproval | None = None
