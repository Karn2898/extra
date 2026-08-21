"""Process-local approval repository for development and tests."""

from __future__ import annotations

import asyncio

from agent_engine.approvals.approval_repository import ApprovalRepository
from agent_engine.approvals.errors import ApprovalNotFound, InvalidStateTransition
from agent_engine.approvals.models import (
    ApprovalRecord,
    ApprovalStatus,
    ensure_approval_transition,
)


class InMemoryApprovalRepository(ApprovalRepository):
    """Approval store with atomic pending-to-resuming claims."""

    def __init__(self) -> None:
        self._approvals: dict[str, ApprovalRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: ApprovalRecord) -> ApprovalRecord:
        async with self._lock:
            self._approvals[record.approval_id] = record
            return record

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        async with self._lock:
            return self._approvals.get(approval_id)

    async def get_by_tool_call(self, run_id: str, tool_call_id: str) -> ApprovalRecord | None:
        async with self._lock:
            for record in self._approvals.values():
                if record.run_id == run_id and record.tool_call_id == tool_call_id:
                    return record
            return None

    async def get_pending_for_run(self, run_id: str) -> ApprovalRecord | None:
        async with self._lock:
            for record in self._approvals.values():
                if record.run_id == run_id and record.status == ApprovalStatus.PENDING:
                    return record
            return None

    async def claim(self, approval_id: str) -> ApprovalRecord:
        """Atomically move PENDING to RESUMING."""
        async with self._lock:
            record = self._approvals.get(approval_id)
            if record is None:
                raise ApprovalNotFound(approval_id)
            ensure_approval_transition(record.status, ApprovalStatus.RESUMING)
            record.transition(ApprovalStatus.RESUMING)
            return record

    async def reject_pending(self, approval_id: str) -> ApprovalRecord:
        """Atomically reject an approval only while it is pending."""
        async with self._lock:
            record = self._approvals.get(approval_id)
            if record is None:
                raise ApprovalNotFound(approval_id)
            if record.status != ApprovalStatus.PENDING:
                raise InvalidStateTransition(
                    "approval", record.status.value, ApprovalStatus.REJECTED.value
                )
            record.transition(ApprovalStatus.REJECTED)
            return record

    async def set_status(self, approval_id: str, target: ApprovalStatus) -> ApprovalRecord:
        async with self._lock:
            record = self._approvals.get(approval_id)
            if record is None:
                raise ApprovalNotFound(approval_id)
            ensure_approval_transition(record.status, target)
            record.transition(target)
            return record
