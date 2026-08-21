"""Pure policy contract for deciding whether a tool call needs approval."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_engine.approvals.invocation import ToolInvocation


@dataclass(frozen=True)
class ApprovalQuery:
    """The inputs a policy may consider, resolved before policy execution."""

    invocation: ToolInvocation
    auto_mode: bool
    session_allowed: bool


class ApprovalPolicy(ABC):
    @abstractmethod
    def requires_approval(self, query: ApprovalQuery) -> bool:
        raise NotImplementedError
