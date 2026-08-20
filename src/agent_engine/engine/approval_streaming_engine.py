"""Optional engine capability for streaming an existing HITL run."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from agent_engine.approvals.decision import ApprovalDecision
from agent_engine.runtime.streaming import RunStreamEvent


class ApprovalStreamingEngine(ABC):
    @abstractmethod
    def resume_stream(
        self,
        run_id: str,
        approval_id: str,
        decision: ApprovalDecision | str,
        *,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
    ) -> AsyncIterator[RunStreamEvent]:
        raise NotImplementedError
