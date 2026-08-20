"""Legacy session-approval contract retained for existing integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_engine.approvals.invocation import SessionApprovalKey


class SessionApprovalStore(ABC):
    @abstractmethod
    async def is_allowed(self, key: SessionApprovalKey) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def allow(self, key: SessionApprovalKey) -> None:
        raise NotImplementedError
