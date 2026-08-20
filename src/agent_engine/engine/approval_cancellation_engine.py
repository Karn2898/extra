"""Optional capability for terminally cancelling a pending HITL run."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ApprovalCancellationEngine(Protocol):
    async def cancel_pending_approval(
        self,
        run_id: str,
        approval_id: str,
        *,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
    ) -> None: ...
