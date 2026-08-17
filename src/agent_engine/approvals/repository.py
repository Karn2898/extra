"""Persistence contracts for approvals and execution idempotency.

The engine depends only on these ``Protocol`` interfaces (Dependency Inversion);
the in-memory implementations back local development and tests. A production
deployment supplies a shared, database-backed implementation with the same
contract so multi-pod resume works. Its atomic approval claim maps to a
conditional ``UPDATE ... WHERE status = 'pending'`` (compare-and-set).
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from agent_engine.approvals.errors import ApprovalNotFound, InvalidStateTransition
from agent_engine.approvals.models import (
    ApprovalRecord,
    ApprovalStatus,
    ToolExecutionRecord,
    ensure_approval_transition,
)


@runtime_checkable
class ApprovalRepository(Protocol):
    async def create(self, record: ApprovalRecord) -> ApprovalRecord: ...
    async def get(self, approval_id: str) -> ApprovalRecord | None: ...
    async def get_by_tool_call(self, run_id: str, tool_call_id: str) -> ApprovalRecord | None: ...
    async def get_pending_for_run(self, run_id: str) -> ApprovalRecord | None: ...
    async def claim(self, approval_id: str) -> ApprovalRecord: ...
    async def reject_pending(self, approval_id: str) -> ApprovalRecord: ...
    async def set_status(self, approval_id: str, target: ApprovalStatus) -> ApprovalRecord: ...


@runtime_checkable
class ToolExecutionRepository(Protocol):
    async def get(self, execution_id: str) -> ToolExecutionRecord | None: ...
    async def start(self, record: ToolExecutionRecord) -> tuple[ToolExecutionRecord, bool]: ...
    async def complete(self, execution_id: str, status: str, result: str) -> None: ...


class InMemoryApprovalRepository:
    """Process-local approval store with an atomic claim primitive.

    ``claim`` performs the PENDING -> RESUMING compare-and-set under a lock so
    that, of many concurrent resume attempts, exactly one wins. In the shared
    database implementation the same guarantee comes from a conditional UPDATE.
    """

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
        """Atomically move PENDING -> RESUMING. Raises on any non-pending state so
        the caller can report 'already processed' rather than double-execute."""
        async with self._lock:
            record = self._approvals.get(approval_id)
            if record is None:
                raise ApprovalNotFound(approval_id)
            # ensure_* raises InvalidStateTransition for RESUMING/APPROVED/REJECTED,
            # which the manager maps to ApprovalAlreadyProcessed.
            ensure_approval_transition(record.status, ApprovalStatus.RESUMING)
            record.transition(ApprovalStatus.RESUMING)
            return record

    async def reject_pending(self, approval_id: str) -> ApprovalRecord:
        """Atomically reject an approval only while it is still pending.

        This compare-and-set races safely with :meth:`claim`: cancellation and
        approval can never both win for the same tool call.
        """
        async with self._lock:
            record = self._approvals.get(approval_id)
            if record is None:
                raise ApprovalNotFound(approval_id)
            if record.status != ApprovalStatus.PENDING:
                # Keep the public failure consistent with ``claim`` while
                # forbidding cancellation of an already-resuming tool call.
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


class InMemoryToolExecutionRepository:
    """Process-local idempotency ledger.

    ``start`` is a create-if-absent: it returns ``(record, created)`` where
    ``created`` is False if an attempt for that ``execution_id`` already exists,
    letting the manager reuse a prior result instead of re-executing.
    """

    def __init__(self) -> None:
        self._records: dict[str, ToolExecutionRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, execution_id: str) -> ToolExecutionRecord | None:
        async with self._lock:
            return self._records.get(execution_id)

    async def start(self, record: ToolExecutionRecord) -> tuple[ToolExecutionRecord, bool]:
        async with self._lock:
            existing = self._records.get(record.execution_id)
            if existing is not None:
                return existing, False
            self._records[record.execution_id] = record
            return record, True

    async def complete(self, execution_id: str, status: str, result: str) -> None:
        async with self._lock:
            record = self._records.get(execution_id)
            if record is not None:
                record.status = status
                record.result = result
