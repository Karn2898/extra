"""Persistence contract for pending tool approvals."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_engine.approvals.models import ApprovalRecord, ApprovalStatus


class ApprovalRepository(ABC):
    @abstractmethod
    async def create(self, record: ApprovalRecord) -> ApprovalRecord:
        raise NotImplementedError

    @abstractmethod
    async def get(self, approval_id: str) -> ApprovalRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_tool_call(self, run_id: str, tool_call_id: str) -> ApprovalRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def get_pending_for_run(self, run_id: str) -> ApprovalRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def claim(self, approval_id: str) -> ApprovalRecord:
        raise NotImplementedError

    @abstractmethod
    async def reject_pending(self, approval_id: str) -> ApprovalRecord:
        raise NotImplementedError

    @abstractmethod
    async def set_status(self, approval_id: str, target: ApprovalStatus) -> ApprovalRecord:
        raise NotImplementedError
