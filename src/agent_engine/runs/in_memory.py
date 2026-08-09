"""Process-local run repository for development and tests."""

from __future__ import annotations

import asyncio

from agent_engine.approvals.models import (
    RunRecord,
    RunStatus,
    can_run_transition,
)
from agent_engine.runs.repository import RunRepository


class InMemoryRunRepository(RunRepository):
    """Process-local implementation of :class:`RunRepository`.

    Operations are serialized only inside this Python process. The adapter is
    adequate for local use and tests, but it does not provide cross-pod
    registration or transition guarantees.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()

    async def create_if_absent(self, record: RunRecord) -> bool:
        """Register ``record`` unless its ``run_id`` is already known.

        The existence check and write share one process-local critical section,
        so exactly one local caller gets ``created=True``. A future shared
        implementation provides the same contract with its own atomic primitive.
        """
        async with self._lock:
            existing = self._runs.get(record.run_id)
            if existing is not None:
                return False
            self._runs[record.run_id] = record
            return True

    async def get(self, run_id: str) -> RunRecord | None:
        async with self._lock:
            return self._runs.get(run_id)

    async def transition_if_allowed(self, run_id: str, target: RunStatus) -> bool:
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None or not can_run_transition(record.status, target):
                return False
            record.transition(target)
            return True
