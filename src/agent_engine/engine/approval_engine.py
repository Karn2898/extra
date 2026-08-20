"""Optional engine capability for inspecting and resuming HITL runs."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_engine.approvals.decision import ApprovalDecision
from agent_engine.engine.types import PendingApproval, RunResult


class ApprovalEngine(ABC):
    @abstractmethod
    async def get_pending_approval(self, run_id: str) -> PendingApproval | None:
        raise NotImplementedError

    @abstractmethod
    async def get_processed_result(
        self,
        run_id: str,
        approval_id: str,
        *,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
    ) -> RunResult | None:
        raise NotImplementedError

    @abstractmethod
    async def resume(
        self,
        run_id: str,
        approval_id: str,
        decision: ApprovalDecision | str,
        *,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
    ) -> RunResult:
        raise NotImplementedError
