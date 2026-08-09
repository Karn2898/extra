"""Process-local run repository for development and tests."""

from __future__ import annotations

import asyncio
import heapq
import math
import time
from collections.abc import Callable

from agent_engine.approvals.errors import InvalidStateTransition
from agent_engine.approvals.models import (
    RunRecord,
    RunStatus,
)

DEFAULT_TERMINAL_RUN_TTL_SECONDS = 86_400.0  # 24 hours

_TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)


class InMemoryRunRepository:
    """Process-local implementation of :class:`RunRepository`.

    Operations are serialized only inside this Python process. The adapter is
    adequate for local use and tests, but it does not provide cross-pod
    registration or transition guarantees. Terminal records are retained for
    ``terminal_ttl_seconds``; active and approval-pending records do not expire.
    """

    def __init__(
        self,
        *,
        terminal_ttl_seconds: float = DEFAULT_TERMINAL_RUN_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not math.isfinite(terminal_ttl_seconds) or terminal_ttl_seconds <= 0:
            raise ValueError("terminal_ttl_seconds must be a positive finite number")
        self._runs: dict[str, RunRecord] = {}
        self._terminal_expirations: list[tuple[float, str]] = []
        self._lock = asyncio.Lock()
        self._terminal_ttl_seconds = terminal_ttl_seconds
        self._clock = clock or time.monotonic

    async def create_if_absent(self, record: RunRecord) -> bool:
        """Register ``record`` unless its ``run_id`` is already known.

        The existence check and write share one process-local critical section,
        so exactly one local caller gets ``created=True``. A future shared
        implementation provides the same contract with its own atomic primitive.
        """
        async with self._lock:
            now = self._clock()
            self._evict_expired(now)
            existing = self._runs.get(record.run_id)
            if existing is not None:
                return False
            self._runs[record.run_id] = record
            if record.status in _TERMINAL_RUN_STATUSES:
                self._schedule_expiration(record.run_id, now)
            return True

    async def get(self, run_id: str) -> RunRecord | None:
        async with self._lock:
            self._evict_expired(self._clock())
            return self._runs.get(run_id)

    async def transition_if_allowed(self, run_id: str, target: RunStatus) -> bool:
        async with self._lock:
            now = self._clock()
            self._evict_expired(now)
            record = self._runs.get(run_id)
            if record is None:
                return False
            try:
                record.transition(target)
            except InvalidStateTransition:
                return False
            if target in _TERMINAL_RUN_STATUSES:
                self._schedule_expiration(run_id, now)
            return True

    def _schedule_expiration(self, run_id: str, now: float) -> None:
        heapq.heappush(
            self._terminal_expirations,
            (now + self._terminal_ttl_seconds, run_id),
        )

    def _evict_expired(self, now: float) -> None:
        while self._terminal_expirations and self._terminal_expirations[0][0] <= now:
            _, run_id = heapq.heappop(self._terminal_expirations)
            record = self._runs.get(run_id)
            if record is not None and record.status in _TERMINAL_RUN_STATUSES:
                self._runs.pop(run_id)
