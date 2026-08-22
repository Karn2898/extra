"""Domain model for observed tool usage.

Persistence-facing types only: what happened to a logical invocation, and the
identity that names it. No LangGraph, LangChain, or prompt concerns.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agent_engine.runtime.tool_models import ToolProviderName


class ToolInvocationStatus(StrEnum):
    """Terminal outcome of one logical invocation.

    Only outcomes the runtime actually observes are modelled. Intermediate
    approval states belong to the approval subsystem, which owns them.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


class ToolInvocationKind(StrEnum):
    """What was invoked: a real tool, or a child agent exposed as one.

    Both are actions an orchestrator or agent took, so both belong to the
    execution history. They are distinguished because the caller-facing run
    trace reports real tool/MCP calls only.
    """

    TOOL = "tool"
    AGENT = "agent"


def stable_tool_call_id(*parts: Any) -> str:
    """Derive a deterministic call id from the call's own identifying parts.

    Deriving it from the call — rather than the provider's message id — is what
    lets one logical invocation keep a single identity across a suspension and
    its resumed replay.
    """
    payload = json.dumps(list(parts), sort_keys=True, separators=(",", ":"), default=str)
    return f"call_{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


@dataclass(frozen=True)
class ToolCallIdentity:
    """Names one logical invocation: ``conversation → run → agent → tool call``.

    ``conversation_id`` gives continuity across the user's turns; ``run_id``
    preserves the exact execution it happened in. ``agent_id`` is the agent's
    own id — the one the approval subsystem also records, and the name the model
    is shown — while ``agent_path`` locates that agent in the graph, so a record
    stays traceable when the same agent id appears under different parents.
    """

    run_id: str
    agent_id: str
    agent_path: str
    tool_call_id: str
    tool_name: str
    provider: ToolProviderName = "local"
    server_id: str | None = None
    conversation_id: str | None = None
    kind: ToolInvocationKind = ToolInvocationKind.TOOL


@dataclass(frozen=True)
class ToolInvocationRecord:
    """The persisted outcome of one logical invocation.

    Immutable, so a repository can hand out records without exposing internals.
    Arguments and results are deliberately absent: they may carry sensitive or
    oversized data and no consumer of tool usage needs them.
    """

    call: ToolCallIdentity
    status: ToolInvocationStatus
    error: str | None = None
    recorded_at: float = field(default_factory=time.time)

    @property
    def key(self) -> tuple[str, str]:
        """The ``(run_id, tool_call_id)`` pair that identifies the invocation."""
        return self.call.run_id, self.call.tool_call_id
