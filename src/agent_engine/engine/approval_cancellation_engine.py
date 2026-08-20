"""Optional capability for terminally cancelling a pending HITL run."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ApprovalCancellationEngine(ABC):
    @abstractmethod
    async def cancel_pending_approval(
        self,
        run_id: str,
        approval_id: str,
        *,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
    ) -> None:
        raise NotImplementedError
