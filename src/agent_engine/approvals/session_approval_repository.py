"""Current persistence contract for session-scoped approval grants."""

from __future__ import annotations

from abc import abstractmethod

from agent_engine.approvals.invocation import (
    SessionApprovalGrant,
    SessionApprovalKey,
    SessionApprovalScope,
)
from agent_engine.approvals.session_approval_store import SessionApprovalStore


class SessionApprovalRepository(SessionApprovalStore):
    @abstractmethod
    async def is_allowed(self, key: SessionApprovalKey) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def allow(
        self, key: SessionApprovalKey, *, grant: SessionApprovalGrant | None = None
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def revoke(self, key: SessionApprovalKey) -> None:
        raise NotImplementedError

    @abstractmethod
    async def clear_session(self, scope: SessionApprovalScope) -> None:
        raise NotImplementedError
